from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str
    image: bytes | None = None
    image_mime_type: str | None = None


@dataclass(frozen=True)
class LLMResponse:
    content: str
    raw: dict = field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    """What every concrete provider (fake, OpenAI, Anthropic, ...) must implement.

    Services depend on this, never on a concrete client, so swapping providers is a
    config change and tests can inject a fake without touching a real API.
    """

    def complete(
        self, messages: list[LLMMessage], tools: list[dict] | None = None
    ) -> LLMResponse: ...


class FakeLLMProvider:
    """Dev/test-only provider. Returns pre-programmed responses instead of calling a real API.

    Real agent code uses GeminiProvider; automated tests inject this instead so they stay
    fast, free, and deterministic — no network call, no API quota, no flake.
    """

    def __init__(self, response: str = "", responses: list[str] | None = None):
        self._responses = list(responses) if responses is not None else None
        self._response = response
        self.calls: list[list[LLMMessage]] = []

    def complete(
        self, messages: list[LLMMessage], tools: list[dict] | None = None
    ) -> LLMResponse:
        self.calls.append(messages)
        if self._responses is not None:
            content = self._responses.pop(0)
        else:
            content = self._response
        return LLMResponse(content=content)
