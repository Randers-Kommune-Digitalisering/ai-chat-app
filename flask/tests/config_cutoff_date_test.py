import importlib
from datetime import datetime


def test_cutoff_date_falls_back_to_default_when_env_is_empty(monkeypatch):
    import utils.config as config

    monkeypatch.setenv('CONVERSATION_LOAD_CUTOFF_DATE', '')
    reloaded = importlib.reload(config)
    assert reloaded.CONVERSATION_LOAD_CUTOFF_DATE == datetime.fromisoformat('2026-09-15')

    monkeypatch.delenv('CONVERSATION_LOAD_CUTOFF_DATE', raising=False)
    importlib.reload(reloaded)


def test_cutoff_date_falls_back_to_default_when_env_is_invalid(monkeypatch):
    import utils.config as config

    monkeypatch.setenv('CONVERSATION_LOAD_CUTOFF_DATE', 'not-a-date')
    reloaded = importlib.reload(config)
    assert reloaded.CONVERSATION_LOAD_CUTOFF_DATE == datetime.fromisoformat('2026-09-15')

    monkeypatch.delenv('CONVERSATION_LOAD_CUTOFF_DATE', raising=False)
    importlib.reload(reloaded)


def test_agent_file_size_limit_parses_units(monkeypatch):
    import utils.config as config

    monkeypatch.setenv('AGENT_FILE_SIZE_LIMIT', '12MB')
    reloaded = importlib.reload(config)
    assert reloaded.AGENT_FILE_SIZE_LIMIT == 12 * 1024 * 1024

    monkeypatch.delenv('AGENT_FILE_SIZE_LIMIT', raising=False)
    importlib.reload(reloaded)


def test_agent_file_size_limit_falls_back_when_invalid(monkeypatch):
    import utils.config as config

    monkeypatch.setenv('AGENT_FILE_SIZE_LIMIT', 'invalid')
    reloaded = importlib.reload(config)
    assert reloaded.AGENT_FILE_SIZE_LIMIT == 10 * 1024 * 1024

    monkeypatch.delenv('AGENT_FILE_SIZE_LIMIT', raising=False)
    importlib.reload(reloaded)
