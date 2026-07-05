from types import SimpleNamespace

from apps.agents.llm import LLMMessage
from apps.agents.providers.gemini import GeminiProvider


class _FakeModels:
    """Stands in for genai.Client().models — no real network call, no real key needed."""

    def __init__(self, response_text):
        self.response_text = response_text
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return SimpleNamespace(text=self.response_text)


class _FakeGenaiClient:
    def __init__(self, response_text):
        self.models = _FakeModels(response_text)


def test_complete_returns_the_response_text():
    client = _FakeGenaiClient(response_text="Staples, $42.50")
    provider = GeminiProvider(client=client, model="gemini-2.5-flash")

    result = provider.complete([LLMMessage(role="user", content="Read this receipt.")])

    assert result.content == "Staples, $42.50"
    assert client.models.calls[0]["model"] == "gemini-2.5-flash"


def test_system_messages_become_system_instruction_not_a_content_turn():
    client = _FakeGenaiClient(response_text="ok")
    provider = GeminiProvider(client=client, model="gemini-2.5-flash")

    provider.complete(
        [
            LLMMessage(role="system", content="You extract receipt data."),
            LLMMessage(role="user", content="Here is a receipt."),
        ]
    )

    call = client.models.calls[0]
    assert call["config"].system_instruction == "You extract receipt data."
    assert len(call["contents"]) == 1


def test_message_image_is_sent_as_an_extra_part():
    client = _FakeGenaiClient(response_text="ok")
    provider = GeminiProvider(client=client, model="gemini-2.5-flash")

    provider.complete(
        [LLMMessage(role="user", content="Read this.", image=b"bytes", image_mime_type="image/jpeg")]
    )

    parts = client.models.calls[0]["contents"][0].parts
    assert len(parts) == 2
    assert parts[0].text == "Read this."
    assert parts[1].inline_data.data == b"bytes"
    assert parts[1].inline_data.mime_type == "image/jpeg"


def test_assistant_role_is_translated_to_geminis_model_role():
    client = _FakeGenaiClient(response_text="ok")
    provider = GeminiProvider(client=client, model="gemini-2.5-flash")

    provider.complete(
        [
            LLMMessage(role="user", content="hi"),
            LLMMessage(role="assistant", content="hello"),
        ]
    )

    roles = [c.role for c in client.models.calls[0]["contents"]]
    assert roles == ["user", "model"]
