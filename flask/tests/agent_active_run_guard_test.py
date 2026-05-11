from types import SimpleNamespace

from azure.ai.agents.models import RunStatus
from utils.azure_openai import Agent


class _Runs:
    def __init__(self, statuses):
        self._runs = [SimpleNamespace(status=s) for s in statuses]

    def list(self, thread_id, order=None):
        return list(self._runs)

    def create_and_process(self, *args, **kwargs):
        raise AssertionError("create_and_process must not be called when a run is active")


class _Messages:
    def create(self, *args, **kwargs):
        raise AssertionError("messages.create must not be called when a run is active")

    def list(self, *args, **kwargs):
        raise AssertionError("messages.list must not be called when a run is active")


class _Agents:
    def __init__(self, statuses):
        self.runs = _Runs(statuses)
        self.messages = _Messages()


class _Project:
    def __init__(self, statuses):
        self.agents = _Agents(statuses)


class _RunsCompleted:
    def list(self, thread_id, order=None):
        return []

    def create_and_process(self, *args, **kwargs):
        return SimpleNamespace(status="completed")


class _MessagesEmpty:
    def create(self, *args, **kwargs):
        return None

    def list(self, *args, **kwargs):
        return []


class _AgentsCompletedNoMessages:
    def __init__(self):
        self.runs = _RunsCompleted()
        self.messages = _MessagesEmpty()


class _ProjectCompletedNoMessages:
    def __init__(self):
        self.agents = _AgentsCompletedNoMessages()


def test_agent_fetch_chat_response_returns_early_when_run_active():
    # Avoid constructing a real AIProjectClient/DefaultAzureCredential.
    agent = Agent.__new__(Agent)
    agent.project = _Project([RunStatus.IN_PROGRESS.value])

    response, refs, error_message = agent.fetch_chat_response(
        chat_message="hello",
        files=[],
        thread_id="thread_test",
        use_alt=False,
    )

    assert response is None
    assert refs == []
    assert error_message is not None


def test_agent_fetch_chat_response_returns_error_when_no_assistant_message():
    # Avoid constructing a real AIProjectClient/DefaultAzureCredential.
    agent = Agent.__new__(Agent)
    agent.project = _ProjectCompletedNoMessages()
    agent.assistant_id = "assistant_test"
    agent.assistant_alt_id = "assistant_alt_test"

    response, refs, error_message = agent.fetch_chat_response(
        chat_message="hello",
        files=[],
        thread_id="thread_test",
        use_alt=False,
    )

    assert response is None
    assert refs == []
    assert error_message is not None
