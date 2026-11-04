from utils.azure_openai import Agent


class _CloseCounter:
    def __init__(self):
        self.calls = 0

    def close(self):
        self.calls += 1


def test_agent_close_is_idempotent():
    # Avoid constructing a real AIProjectClient/DefaultAzureCredential.
    agent = Agent.__new__(Agent)

    client = _CloseCounter()
    project = _CloseCounter()
    credential = _CloseCounter()

    agent.client = client
    agent._project = project
    agent._credential = credential
    agent._closed = False

    agent.close()
    agent.close()

    assert client.calls == 1
    assert project.calls == 1
    assert credential.calls == 1
