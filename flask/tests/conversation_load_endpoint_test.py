import time
from contextlib import contextmanager

import pytest


def _generate_rsa_keypair_pem():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    return private_pem, public_pem


def _sign_permit(*, private_pem: str, payload: dict, kid: str = "v1") -> str:
    from authlib.jose import JsonWebToken

    jwt = JsonWebToken(["RS256"])
    header = {"alg": "RS256", "typ": "JWT", "kid": kid}
    token = jwt.encode(header, payload, private_pem)
    if isinstance(token, (bytes, bytearray)):
        return token.decode("utf-8")
    return str(token)


@pytest.fixture()
def app(monkeypatch):
    # Import after pytest-env in other tests have set required env vars.
    from main import create_app

    app = create_app()
    app.config.update({"TESTING": True})
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def test_load_conversation_requires_valid_permit(client):
    res = client.post('/api/conversations/load', json={})
    assert res.status_code == 401


def test_load_conversation_by_permit_happy_path(client, monkeypatch):
    import utils.config as config
    import api_endpoints as api

    private_pem, public_pem = _generate_rsa_keypair_pem()

    monkeypatch.setattr(config, "CONVERSATION_LOAD_PERMIT_RS_PUBLIC_KEY_PEM", public_pem)
    monkeypatch.setattr(config, "CONVERSATION_LOAD_PERMIT_ISSUER", "gpt-dashboard-portal")
    monkeypatch.setattr(config, "CONVERSATION_LOAD_PERMIT_AUDIENCE", "chat-app")
    monkeypatch.setattr(config, "CONVERSATION_LOAD_PERMIT_ALLOWED_KIDS", ["v1"])

    now = int(time.time())
    payload = {
        "iss": config.CONVERSATION_LOAD_PERMIT_ISSUER,
        "aud": config.CONVERSATION_LOAD_PERMIT_AUDIENCE,
        "iat": now,
        "exp": now + 60,
        "conversation_id": 42,
        "user_email": "user@example.com",
    }
    token = _sign_permit(private_pem=private_pem, payload=payload, kid="v1")

    class _FakeConversation:
        def to_dict(self, include_messages: bool = False):
            return {
                "id": 42,
                "user_email": "user@example.com",
                "messages": [],
                "thread_id": None,
                "title": "Test",
                "gpt_id": "x",
                "created_at": "2020-01-01T00:00:00",
                "updated_at": "2020-01-01T00:00:00",
                "is_active": True,
            }

    @contextmanager
    def _fake_session_scope():
        yield object()

    monkeypatch.setattr(api, "get_user_conversation", lambda session, user_email, conversation_id: _FakeConversation())
    monkeypatch.setattr(api.db_client, "session_scope", _fake_session_scope)

    res = client.post('/api/conversations/load', headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["conversation"]["id"] == 42
    assert data["conversation"]["user_email"] == "user@example.com"
