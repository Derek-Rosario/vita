import json
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from assistant.constants import twilio_approved_call_cache_key
from assistant.services.chat_service import AssistantService
from assistant.prompt import get_system_prompt, get_voice_system_prompt
from assistant.services.llm import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ToolCall,
    ToolSpec,
)
from assistant.services.llm.exceptions import LLMConfigurationError
from assistant.services.llm.factory import get_provider
from assistant.services.llm.providers.openai_chatgpt import OpenAIChatGPTProvider
from assistant.tools import (
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    get_default_registry,
)
from tasks.models import Comment, Routine, RoutineStep, Task, TaskStatus


class _FakeCompletions:
    def __init__(self, response):
        self._response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self._response


class _FakeOpenAIClient:
    def __init__(self, response):
        self._completions = _FakeCompletions(response)
        self.chat = SimpleNamespace(completions=self._completions)


class _CapturingProvider:
    def __init__(self, response_content: str = "ok"):
        self.response_content = response_content
        self.last_request = None

    def chat(self, request):
        self.last_request = request
        return ChatResponse(provider="fake", model="fake-model", content=self.response_content)


class _ToolLoopProvider:
    def __init__(self):
        self.calls = 0
        self.requests = []

    def chat(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.calls == 1:
            return ChatResponse(
                provider="fake",
                model="fake-model",
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="echo_tool",
                        arguments={"text": "hello"},
                    )
                ],
            )

        return ChatResponse(
            provider="fake",
            model="fake-model",
            content="Tool execution complete.",
        )


class OpenAIProviderTests(SimpleTestCase):
    def test_chat_maps_messages_and_returns_content(self):
        response = SimpleNamespace(
            model="gpt-4o-mini",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="hello from model"),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
        )
        fake_client = _FakeOpenAIClient(response=response)
        provider = OpenAIChatGPTProvider(
            api_key="test-key",
            default_model="gpt-4o-mini",
            client=fake_client,
        )

        result = provider.chat(
            ChatRequest(
                messages=[ChatMessage(role="user", content="Say hi")],
                temperature=0.2,
                max_output_tokens=128,
            )
        )

        self.assertEqual(result.provider, "openai")
        self.assertEqual(result.model, "gpt-4o-mini")
        self.assertEqual(result.content, "hello from model")
        self.assertIsNotNone(result.usage)
        self.assertEqual(result.usage.total_tokens, 18)
        self.assertEqual(
            fake_client.chat.completions.kwargs["messages"],
            [{"role": "user", "content": "Say hi"}],
        )
        self.assertEqual(fake_client.chat.completions.kwargs["max_completion_tokens"], 128)

    def test_chat_parses_tool_calls_and_sends_tool_specs(self):
        response = SimpleNamespace(
            model="gpt-4o-mini",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="",
                        tool_calls=[
                            SimpleNamespace(
                                id="call_1",
                                function=SimpleNamespace(
                                    name="tasks_create_task",
                                    arguments='{"title":"Write tests"}',
                                ),
                            )
                        ],
                    ),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=8, completion_tokens=3, total_tokens=11),
        )
        fake_client = _FakeOpenAIClient(response=response)
        provider = OpenAIChatGPTProvider(
            api_key="test-key",
            default_model="gpt-4o-mini",
            client=fake_client,
        )

        result = provider.chat(
            ChatRequest(
                messages=[ChatMessage(role="user", content="create a task")],
                tools=[
                    ToolSpec(
                        name="tasks_create_task",
                        description="Create a task",
                        input_schema={"type": "object", "properties": {}},
                    )
                ],
            )
        )

        self.assertIsNotNone(result.tool_calls)
        self.assertEqual(result.tool_calls[0].name, "tasks_create_task")
        self.assertEqual(result.tool_calls[0].arguments["title"], "Write tests")
        self.assertEqual(fake_client.chat.completions.kwargs["tools"][0]["type"], "function")


class ProviderFactoryTests(SimpleTestCase):
    @override_settings(
        ASSISTANT_LLM_PROVIDER="openai",
        ASSISTANT_OPENAI_MODEL="gpt-4o-mini",
        OPENAI_API_KEY="test-key",
    )
    def test_factory_builds_openai_provider(self):
        with patch("assistant.services.llm.factory.OpenAIChatGPTProvider") as provider_cls:
            get_provider()

        provider_cls.assert_called_once_with(
            api_key="test-key",
            default_model="gpt-4o-mini",
        )

    @override_settings(ASSISTANT_LLM_PROVIDER="unknown-provider")
    def test_factory_rejects_unknown_provider(self):
        with self.assertRaises(LLMConfigurationError):
            get_provider()


class AssistantServiceTests(SimpleTestCase):
    def test_reply_builds_message_stack(self):
        provider = _CapturingProvider(response_content="done")
        service = AssistantService(provider=provider)
        history = [ChatMessage(role="assistant", content="How can I help?")]

        result = service.reply(
            "Create a task for tomorrow",
            system_message="You are the Vita assistant.",
            history=history,
        )

        self.assertEqual(result.content, "done")
        self.assertFalse(result.tool_calls_executed)
        self.assertIsNotNone(provider.last_request)
        self.assertEqual(provider.last_request.messages[0].role, "system")
        self.assertEqual(provider.last_request.messages[1].role, "assistant")
        self.assertEqual(provider.last_request.messages[2].role, "user")

    def test_reply_executes_tool_calls_then_returns_final_message(self):
        provider = _ToolLoopProvider()
        registry = ToolRegistry()

        def _echo_tool_handler(args, context):
            return ToolResult(
                ok=True,
                data={"echoed": args["text"], "user": context.user.username},
            )

        registry.register(
            ToolDefinition(
                name="echo_tool",
                description="Echo text",
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
                handler=_echo_tool_handler,
            )
        )
        service = AssistantService(provider=provider, registry=registry)

        fake_user = SimpleNamespace(
            username="assistant-user",
            is_authenticated=True,
            is_superuser=True,
        )
        result = service.reply(
            "run tool",
            tool_context=ToolContext(user=fake_user),
        )

        self.assertEqual(result.content, "Tool execution complete.")
        self.assertTrue(result.tool_calls_executed)
        self.assertEqual(provider.calls, 2)
        second_call = provider.requests[1]
        self.assertEqual(second_call.messages[-1].role, "tool")
        payload = json.loads(second_call.messages[-1].content)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["echoed"], "hello")


class AssistantPromptTests(SimpleTestCase):
    @override_settings(
        ASSISTANT_SYSTEM_PROMPT="Override prompt",
        ASSISTANT_SYSTEM_PROMPT_FILE="assistant/system_prompt.txt",
        ASSISTANT_SYSTEM_PROMPT_DEFAULT="Default prompt",
    )
    def test_prompt_uses_direct_setting_override(self):
        self.assertEqual(get_system_prompt(), "Override prompt")

    @override_settings(
        ASSISTANT_SYSTEM_PROMPT="",
        ASSISTANT_SYSTEM_PROMPT_DEFAULT="Default prompt",
    )
    def test_prompt_uses_file_when_available(self):
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt") as handle:
            handle.write("File prompt")
            handle.flush()
            with override_settings(ASSISTANT_SYSTEM_PROMPT_FILE=handle.name):
                self.assertEqual(get_system_prompt(), "File prompt")

    @override_settings(
        ASSISTANT_SYSTEM_PROMPT="",
        ASSISTANT_SYSTEM_PROMPT_FILE="assistant/does-not-exist.txt",
        ASSISTANT_SYSTEM_PROMPT_DEFAULT="Default prompt",
    )
    def test_prompt_falls_back_to_default(self):
        self.assertEqual(get_system_prompt(), "Default prompt")

    @override_settings(
        ASSISTANT_VOICE_SYSTEM_PROMPT="Voice override prompt",
        ASSISTANT_VOICE_SYSTEM_PROMPT_FILE="assistant/system_prompt_voice.txt",
        ASSISTANT_VOICE_SYSTEM_PROMPT_DEFAULT="Voice default prompt",
    )
    def test_voice_prompt_uses_direct_setting_override(self):
        self.assertEqual(get_voice_system_prompt(), "Voice override prompt")


@override_settings(
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
)
class AssistantChatViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="assistant_tester",
            email="assistant@example.com",
            password="secret123",
        )
        self.client.force_login(self.user)

    def test_get_chat_page_renders(self):
        response = self.client.get(reverse("assistant_chat"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Assistant")
        self.assertContains(response, 'hx-ext="sse"')

    def test_widget_renders_on_board_page(self):
        response = self.client.get(reverse("task_board"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="assistant-widget"')

    @patch("assistant.views.schedule_assistant_reply")
    def test_send_message_appends_user_message_and_schedules_reply(self, schedule_mock):
        response = self.client.post(
            reverse("assistant_send_message"),
            {"message": "Help me plan today"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Help me plan today")

        history = self.client.session["assistant_chat_history"]
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "Help me plan today")
        self.assertEqual(len(history), 1)
        schedule_mock.assert_called_once()

    def test_clear_chat_empties_history(self):
        session = self.client.session
        session["assistant_chat_history"] = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        session.save()

        response = self.client.post(
            reverse("assistant_clear_chat"),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session["assistant_chat_history"], [])

    @override_settings(
        TWILIO_CONVERSATION_RELAY_WS_URL="",
        TWILIO_VALIDATE_SIGNATURES=False,
        TO_PHONE_NUMBER="+15551234567",
    )
    def test_twilio_twiml_endpoint_renders_conversationrelay(self):
        self.client.logout()
        response = self.client.post(
            reverse("assistant_twilio_conversation_relay_twiml"),
            data={"From": "+15551234567", "To": "+15550001111"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<ConversationRelay", html=False)
        self.assertContains(
            response,
            'url="ws://testserver/ws/twilio/conversation-relay/"',
            html=False,
        )

    @override_settings(
        TWILIO_VALIDATE_SIGNATURES=False,
        TO_PHONE_NUMBER="+15551234567",
    )
    def test_twilio_twiml_endpoint_allows_when_to_matches_personal_number(self):
        self.client.logout()
        response = self.client.post(
            reverse("assistant_twilio_conversation_relay_twiml"),
            data={"From": "+15550001111", "To": "+15551234567"},
        )

        self.assertEqual(response.status_code, 200)

    @override_settings(
        TWILIO_VALIDATE_SIGNATURES=False,
        TO_PHONE_NUMBER="+15551234567",
    )
    def test_twilio_twiml_endpoint_rejects_unknown_numbers(self):
        self.client.logout()
        response = self.client.post(
            reverse("assistant_twilio_conversation_relay_twiml"),
            data={"From": "+15559998888", "To": "+15550001111"},
        )

        self.assertEqual(response.status_code, 403)


@override_settings(
    TWILIO_VALIDATE_SIGNATURES=False,
)
class ConversationRelayConsumerTests(SimpleTestCase):
    def test_prompt_and_interrupt_keep_history_consistent(self):
        captured_histories: list[list[tuple[str, str]]] = []
        responses = iter(
            [
                ChatResponse(provider="fake", model="fake-model", content="First answer"),
                ChatResponse(provider="fake", model="fake-model", content="Second answer"),
            ]
        )

        def _reply(*args, **kwargs):
            history = kwargs.get("history", [])
            captured_histories.append([(message.role, message.content) for message in history])
            return next(responses)

        reply_mock = Mock(side_effect=_reply)
        service_mock = SimpleNamespace(reply=reply_mock)

        with patch("assistant.consumers.AssistantService", return_value=service_mock):
            from vita.asgi import application

            async def run():
                communicator = WebsocketCommunicator(
                    application, "/ws/twilio/conversation-relay/"
                )
                connected, _ = await communicator.connect()
                self.assertTrue(connected)

                await communicator.send_json_to({"type": "setup", "callSid": "CA123"})
                await communicator.send_json_to(
                    {"type": "prompt", "voicePrompt": "hello there", "last": True}
                )
                first_message = await communicator.receive_json_from()
                self.assertEqual(first_message["type"], "text")
                self.assertEqual(first_message["token"], "First answer")
                self.assertTrue(first_message["last"])

                await communicator.send_json_to(
                    {"type": "interrupt", "utteranceUntilInterrupt": "First"}
                )
                await communicator.send_json_to(
                    {"type": "prompt", "voicePrompt": "follow up", "last": True}
                )
                second_message = await communicator.receive_json_from()
                self.assertEqual(second_message["token"], "Second answer")
                self.assertTrue(second_message["last"])

                await communicator.disconnect()

            async_to_sync(run)()

        self.assertEqual(reply_mock.call_count, 2)
        self.assertEqual(captured_histories[0], [])
        self.assertEqual(
            captured_histories[1],
            [("user", "hello there"), ("assistant", "First")],
        )

    def test_tools_enabled_only_for_approved_twilio_call(self):
        captured_enable_tools: list[bool] = []

        def _reply(*args, **kwargs):
            captured_enable_tools.append(bool(kwargs.get("enable_tools")))
            return ChatResponse(provider="fake", model="fake-model", content="Done")

        reply_mock = Mock(side_effect=_reply)
        service_mock = SimpleNamespace(reply=reply_mock)
        fake_user = SimpleNamespace(is_superuser=True)

        cache.set(twilio_approved_call_cache_key("CA_APPROVED"), True, timeout=60)

        with (
            patch("assistant.consumers.AssistantService", return_value=service_mock),
            patch("assistant.consumers.ConversationRelayConsumer._build_tool_context")
            as build_tool_context_mock,
        ):
            build_tool_context_mock.return_value = ToolContext(user=fake_user)
            from vita.asgi import application

            async def run():
                approved = WebsocketCommunicator(application, "/ws/twilio/conversation-relay/")
                connected, _ = await approved.connect()
                self.assertTrue(connected)
                await approved.send_json_to({"type": "setup", "callSid": "CA_APPROVED"})
                await approved.send_json_to(
                    {"type": "prompt", "voicePrompt": "approved", "last": True}
                )
                await approved.receive_json_from()
                await approved.disconnect()

                unapproved = WebsocketCommunicator(
                    application, "/ws/twilio/conversation-relay/"
                )
                connected, _ = await unapproved.connect()
                self.assertTrue(connected)
                await unapproved.send_json_to({"type": "setup", "callSid": "CA_REJECTED"})
                await unapproved.send_json_to(
                    {"type": "prompt", "voicePrompt": "unapproved", "last": True}
                )
                await unapproved.receive_json_from()
                await unapproved.disconnect()

            async_to_sync(run)()

        self.assertEqual(reply_mock.call_count, 2)
        self.assertEqual(captured_enable_tools, [True, False])


class TaskToolIntegrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="task_tool_user",
            email="task_tool@example.com",
            password="secret123",
        )

    def test_tasks_create_task_tool_creates_task(self):
        registry = get_default_registry()
        tool = registry.get("tasks_create_task")
        self.assertIsNotNone(tool)

        result = tool.handler(
            {"title": "Created via tool", "status": "todo"},
            ToolContext(user=self.user),
        )

        self.assertTrue(result.ok)
        self.assertTrue(Task.objects.filter(title="Created via tool").exists())

    def test_tasks_find_tasks_returns_matching_tasks(self):
        Task.objects.create(title="Plan Monday", status=TaskStatus.TODO)
        Task.objects.create(title="Buy groceries", status=TaskStatus.BACKLOG)

        registry = get_default_registry()
        tool = registry.get("tasks_find_tasks")
        self.assertIsNotNone(tool)

        result = tool.handler(
            {"query": "plan", "include_done": False},
            ToolContext(user=self.user),
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.data["count"], 1)
        self.assertEqual(result.data["tasks"][0]["title"], "Plan Monday")

    def test_task_state_tools_move_done_comment_and_promote(self):
        task = Task.objects.create(title="Draft report", status=TaskStatus.BACKLOG)

        registry = get_default_registry()
        promote_tool = registry.get("tasks_promote_backlog_task")
        move_tool = registry.get("tasks_move_task_status")
        done_tool = registry.get("tasks_mark_task_done")
        comment_tool = registry.get("tasks_add_comment")
        self.assertIsNotNone(promote_tool)
        self.assertIsNotNone(move_tool)
        self.assertIsNotNone(done_tool)
        self.assertIsNotNone(comment_tool)

        promote_result = promote_tool.handler(
            {"task_id": task.id},
            ToolContext(user=self.user),
        )
        self.assertTrue(promote_result.ok)

        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.TODO)

        move_result = move_tool.handler(
            {"task_id": task.id, "status": TaskStatus.IN_PROGRESS},
            ToolContext(user=self.user),
        )
        self.assertTrue(move_result.ok)

        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

        done_result = done_tool.handler(
            {"task_id": task.id},
            ToolContext(user=self.user),
        )
        self.assertTrue(done_result.ok)

        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.DONE)
        self.assertIsNotNone(task.completed_at)

        comment_result = comment_tool.handler(
            {"task_id": task.id, "content": "Finished and verified."},
            ToolContext(user=self.user),
        )
        self.assertTrue(comment_result.ok)
        self.assertTrue(
            Comment.objects.filter(task=task, content="Finished and verified.").exists()
        )

    def test_routine_step_crud_tools(self):
        routine = Routine.objects.create(name="Morning")
        registry = get_default_registry()
        create_tool = registry.get("tasks_create_routine_step")
        list_tool = registry.get("tasks_list_routine_steps")
        update_tool = registry.get("tasks_update_routine_step")
        delete_tool = registry.get("tasks_delete_routine_step")
        self.assertIsNotNone(create_tool)
        self.assertIsNotNone(list_tool)
        self.assertIsNotNone(update_tool)
        self.assertIsNotNone(delete_tool)

        create_result = create_tool.handler(
            {
                "routine_id": routine.id,
                "title": "Hydrate",
                "sort_order": 1,
                "default_energy": "LOW",
            },
            ToolContext(user=self.user),
        )
        self.assertTrue(create_result.ok)
        step_id = create_result.data["routine_step"]["id"]
        step = RoutineStep.objects.get(pk=step_id)
        self.assertEqual(step.title, "Hydrate")

        list_result = list_tool.handler(
            {"routine_id": routine.id},
            ToolContext(user=self.user),
        )
        self.assertTrue(list_result.ok)
        self.assertEqual(list_result.data["count"], 1)

        update_result = update_tool.handler(
            {"routine_step_id": step_id, "title": "Drink water", "is_stackable": True},
            ToolContext(user=self.user),
        )
        self.assertTrue(update_result.ok)
        step.refresh_from_db()
        self.assertEqual(step.title, "Drink water")
        self.assertTrue(step.is_stackable)

        delete_result = delete_tool.handler(
            {"routine_step_id": step_id},
            ToolContext(user=self.user),
        )
        self.assertTrue(delete_result.ok)
        self.assertFalse(RoutineStep.objects.filter(pk=step_id).exists())

    def test_assistant_service_can_execute_tasks_tool_call(self):
        class _Provider:
            def __init__(self):
                self.calls = 0

            def chat(self, request):
                self.calls += 1
                if self.calls == 1:
                    return ChatResponse(
                        provider="fake",
                        model="fake-model",
                        content="",
                        tool_calls=[
                            ToolCall(
                                id="call_1",
                                name="tasks_create_task",
                                arguments={"title": "Plan Monday", "status": "todo"},
                            )
                        ],
                    )
                return ChatResponse(
                    provider="fake",
                    model="fake-model",
                    content="Created it.",
                )

        provider = _Provider()
        service = AssistantService(provider=provider, registry=get_default_registry())
        result = service.reply(
            "Create a task",
            tool_context=ToolContext(user=self.user),
        )

        self.assertEqual(result.content, "Created it.")
        self.assertTrue(Task.objects.filter(title="Plan Monday").exists())


class AssistantFormattingTemplateTests(SimpleTestCase):
    def test_assistant_markdown_is_rendered(self):
        template = Template(
            "{% load assistant_formatting %}{{ text|render_chat_message:'assistant' }}"
        )
        rendered = template.render(
            Context({"text": "**Bold**\n\n- Item 1\n- Item 2"})
        )

        self.assertIn("<strong>Bold</strong>", rendered)
        self.assertIn("<li>Item 1</li>", rendered)
        self.assertIn("<li>Item 2</li>", rendered)

    def test_assistant_html_is_sanitized(self):
        template = Template(
            "{% load assistant_formatting %}{{ text|render_chat_message:'assistant' }}"
        )
        rendered = template.render(
            Context({"text": '<script>alert("xss")</script><b>safe</b>'})
        )

        self.assertNotIn("<script>", rendered)
        self.assertIn("safe", rendered)

    def test_user_text_is_escaped(self):
        template = Template(
            "{% load assistant_formatting %}{{ text|render_chat_message:'user' }}"
        )
        rendered = template.render(Context({"text": "<b>hello</b>\nworld"}))

        self.assertIn("&lt;b&gt;hello&lt;/b&gt;<br>world", rendered)

    def test_entity_link_tokens_are_rendered_as_highlighted_links(self):
        template = Template(
            "{% load assistant_formatting %}{{ text|render_chat_message:'assistant' }}"
        )
        rendered = template.render(
            Context(
                {
                    "text": (
                        "Updated [[task:42|Fix auth bug]] and "
                        "[[routine:9|Morning routine]]."
                    )
                }
            )
        )

        self.assertIn('href="/tasks/task/42/edit/"', rendered)
        self.assertIn('href="/tasks/routines/9/"', rendered)
        self.assertIn("assistant-entity-link", rendered)

    def test_contact_link_token_is_rendered_with_search_url(self):
        template = Template(
            "{% load assistant_formatting %}{{ text|render_chat_message:'assistant' }}"
        )
        rendered = template.render(
            Context({"text": "Reach out to [[contact:Alice Johnson]]."})
        )

        self.assertIn('href="/social/contacts?search=Alice+Johnson"', rendered)
        self.assertIn("Alice Johnson", rendered)

    def test_timestamp_token_is_rendered_as_human_datetime(self):
        template = Template(
            "{% load assistant_formatting %}{{ text|render_chat_message:'assistant' }}"
        )
        rendered = template.render(
            Context({"text": "Done by [[ts:2026-02-16T14:30:00-05:00]]."})
        )

        self.assertIn('class="assistant-timestamp"', rendered)
        self.assertIn("Feb 16, 2026", rendered)
        self.assertIn("2:30 PM", rendered)

    def test_timestamp_date_token_is_rendered(self):
        template = Template(
            "{% load assistant_formatting %}{{ text|render_chat_message:'assistant' }}"
        )
        rendered = template.render(Context({"text": "Scheduled [[ts:2026-02-16]]."}))

        self.assertIn('class="assistant-timestamp"', rendered)
        self.assertIn("Mon, Feb 16, 2026", rendered)

    def test_followup_token_is_rendered_as_clickable_chip(self):
        template = Template(
            "{% load assistant_formatting %}{{ text|render_chat_message:'assistant' }}"
        )
        rendered = template.render(
            Context({"text": "Next [[suggest:Mark done|Mark task 42 as done]]."})
        )

        self.assertIn('class="assistant-followup-chip"', rendered)
        self.assertIn('data-assistant-followup="1"', rendered)
        self.assertIn('data-followup-reply="Mark task 42 as done"', rendered)
        self.assertIn(">Mark done<", rendered)
