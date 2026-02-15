import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from assistant.services.chat_service import AssistantService
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
from tasks.models import Task


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
        self.assertEqual(provider.calls, 2)
        second_call = provider.requests[1]
        self.assertEqual(second_call.messages[-1].role, "tool")
        payload = json.loads(second_call.messages[-1].content)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["echoed"], "hello")


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

    @patch("assistant.views.AssistantService.reply")
    def test_post_message_appends_user_and_assistant_messages(self, reply_mock):
        reply_mock.return_value = ChatResponse(
            provider="openai",
            model="gpt-4o-mini",
            content="I can help with that.",
        )

        response = self.client.post(
            reverse("assistant_chat"),
            {"message": "Help me plan today"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("assistant_chat"))

        history = self.client.session["assistant_chat_history"]
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "Help me plan today")
        self.assertEqual(history[1]["role"], "assistant")
        self.assertEqual(history[1]["content"], "I can help with that.")

    def test_post_clear_empties_history(self):
        session = self.client.session
        session["assistant_chat_history"] = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        session.save()

        response = self.client.post(reverse("assistant_chat"), {"action": "clear"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session["assistant_chat_history"], [])


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
