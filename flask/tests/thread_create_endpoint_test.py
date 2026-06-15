from json import JSONDecodeError
from unittest.mock import patch

import pytest


@pytest.fixture()
def app():
    from main import create_app

    app = create_app()
    app.config.update({
        "TESTING": True,
    })
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def test_create_thread_returns_503_on_azure_exception(client):
    with patch(
        "api_endpoints.azure_client.create_thread",
        side_effect=JSONDecodeError("Expecting value", "", 0),
        create=True,
    ):
        res = client.post("/api/threads")

    assert res.status_code == 503
    body = res.get_json()
    assert body["success"] is False
    assert "midlertidig" in body["message"].lower()
