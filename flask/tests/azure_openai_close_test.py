from utils.azure_openai import Agent


class _CloseCounter:
    def __init__(self):
        self.calls = 0

    def close(self):
        self.calls += 1


def test_agent_close_is_idempotent():
    # Avoid constructing a real AIProjectClient/DefaultAzureCredential.
    agent = Agent.__new__(Agent)

    project = _CloseCounter()
    transport = _CloseCounter()
    session = _CloseCounter()

    agent.project = project
    agent._transport = transport
    agent._session = session
    agent._closed = False

    agent.close()
    agent.close()

    assert project.calls == 1
    assert transport.calls == 1
    assert session.calls == 1
