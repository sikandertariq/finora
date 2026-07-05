from apps.agents.llm import FakeLLMProvider, LLMMessage, LLMProvider, LLMResponse


def test_fake_provider_satisfies_the_protocol():
    provider: LLMProvider = FakeLLMProvider(response="hello")
    assert isinstance(provider, LLMProvider)


def test_fake_provider_returns_its_canned_response():
    provider = FakeLLMProvider(response="canned")
    result = provider.complete([LLMMessage(role="user", content="hi")])
    assert result == LLMResponse(content="canned")


def test_fake_provider_records_the_messages_it_was_called_with():
    provider = FakeLLMProvider(response="canned")
    messages = [LLMMessage(role="user", content="hi")]

    provider.complete(messages)

    assert provider.calls == [messages]


def test_fake_provider_can_return_a_queue_of_different_responses():
    provider = FakeLLMProvider(responses=["first", "second"])

    first = provider.complete([LLMMessage(role="user", content="one")])
    second = provider.complete([LLMMessage(role="user", content="two")])

    assert (first.content, second.content) == ("first", "second")
