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
