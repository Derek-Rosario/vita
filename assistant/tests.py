from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from assistant.services.chat_service import AssistantService
from assistant.services.llm import ChatMessage, ChatRequest, ChatResponse
from assistant.services.llm.exceptions import LLMConfigurationError
from assistant.services.llm.factory import get_provider
from assistant.services.llm.providers.openai_chatgpt import OpenAIChatGPTProvider


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
