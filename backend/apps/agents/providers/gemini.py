from google import genai
from google.genai import types

from apps.agents.llm import LLMMessage, LLMResponse

_ROLE_MAP = {"assistant": "model", "user": "user"}


class GeminiProvider:
    """Real LLMProvider backed by Google's Gemini API.

    Constructor takes an already-built ``genai.Client`` rather than an API key, so tests
    can inject a fake client instead of needing network access or a live key.
    """

    def __init__(self, client: genai.Client, model: str):
        self._client = client
        self._model = model

    @classmethod
    def from_settings(cls, api_key: str, model: str) -> "GeminiProvider":
        return cls(client=genai.Client(api_key=api_key), model=model)

    def complete(
        self, messages: list[LLMMessage], tools: list[dict] | None = None
    ) -> LLMResponse:
        system_instruction = "\n".join(m.content for m in messages if m.role == "system") or None
        contents = [
            types.Content(role=_ROLE_MAP.get(m.role, "user"), parts=[types.Part(text=m.content)])
            for m in messages
            if m.role != "system"
        ]
        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system_instruction),
        )
        return LLMResponse(content=response.text or "")
