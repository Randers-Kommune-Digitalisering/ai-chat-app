from utils.azure_openai import Agent


def test_agent_fetch_chat_response_returns_error_when_thread_id_is_missing():
    # Avoid constructing a real AIProjectClient/DefaultAzureCredential.
    agent = Agent.__new__(Agent)

    response, refs, error_message, status = agent.fetch_chat_response(
        chat_message="hello",
        files=[],
        thread_id=None,
        use_alt=False,
    )

    assert response is None
    assert refs == []
    assert error_message is not None
    assert status == 400
