import time

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


def test_verify_conversation_load_permit_success(monkeypatch):
    import utils.config as config
    from utils.conversation_permits import verify_conversation_load_permit

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
        "conversation_id": 123,
        "user_email": "user@example.com",
        "sub": "user@example.com",
    }
    token = _sign_permit(private_pem=private_pem, payload=payload, kid="v1")

    permit = verify_conversation_load_permit(token)
    assert permit.conversation_id == 123
    assert permit.user_email == "user@example.com"


def test_verify_conversation_load_permit_requires_user_email(monkeypatch):
    import utils.config as config
    from utils.conversation_permits import ConversationLoadPermitError, verify_conversation_load_permit

    private_pem, public_pem = _generate_rsa_keypair_pem()

    monkeypatch.setattr(config, "CONVERSATION_LOAD_PERMIT_RS_PUBLIC_KEY_PEM", public_pem)
    monkeypatch.setattr(config, "CONVERSATION_LOAD_PERMIT_ISSUER", "gpt-dashboard-portal")
    monkeypatch.setattr(config, "CONVERSATION_LOAD_PERMIT_AUDIENCE", "chat-app")
    monkeypatch.setattr(config, "CONVERSATION_LOAD_PERMIT_ALLOWED_KIDS", [])

    now = int(time.time())
    payload = {
        "iss": config.CONVERSATION_LOAD_PERMIT_ISSUER,
        "aud": config.CONVERSATION_LOAD_PERMIT_AUDIENCE,
        "iat": now,
        "exp": now + 60,
        "conversation_id": 123,
        # missing user_email
    }
    token = _sign_permit(private_pem=private_pem, payload=payload)

    with pytest.raises(ConversationLoadPermitError):
        verify_conversation_load_permit(token)


def test_verify_conversation_load_permit_rejects_wrong_audience(monkeypatch):
    import utils.config as config
    from utils.conversation_permits import ConversationLoadPermitError, verify_conversation_load_permit

    private_pem, public_pem = _generate_rsa_keypair_pem()

    monkeypatch.setattr(config, "CONVERSATION_LOAD_PERMIT_RS_PUBLIC_KEY_PEM", public_pem)
    monkeypatch.setattr(config, "CONVERSATION_LOAD_PERMIT_ISSUER", "gpt-dashboard-portal")
    monkeypatch.setattr(config, "CONVERSATION_LOAD_PERMIT_AUDIENCE", "chat-app")
    monkeypatch.setattr(config, "CONVERSATION_LOAD_PERMIT_ALLOWED_KIDS", [])

    now = int(time.time())
    payload = {
        "iss": config.CONVERSATION_LOAD_PERMIT_ISSUER,
        "aud": "someone-else",
        "iat": now,
        "exp": now + 60,
        "conversation_id": 123,
        "user_email": "user@example.com",
    }
    token = _sign_permit(private_pem=private_pem, payload=payload)

    with pytest.raises(ConversationLoadPermitError):
        verify_conversation_load_permit(token)


def test_verify_conversation_load_permit_enforces_kid_allowlist(monkeypatch):
    import utils.config as config
    from utils.conversation_permits import ConversationLoadPermitError, verify_conversation_load_permit

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
        "conversation_id": 123,
        "user_email": "user@example.com",
    }
    token = _sign_permit(private_pem=private_pem, payload=payload, kid="v1")

    with pytest.raises(ConversationLoadPermitError):
        verify_conversation_load_permit(token)


def test_verify_conversation_load_permit_rejects_sub_mismatch(monkeypatch):
    import utils.config as config
    from utils.conversation_permits import ConversationLoadPermitError, verify_conversation_load_permit

    private_pem, public_pem = _generate_rsa_keypair_pem()

    monkeypatch.setattr(config, "CONVERSATION_LOAD_PERMIT_RS_PUBLIC_KEY_PEM", public_pem)
    monkeypatch.setattr(config, "CONVERSATION_LOAD_PERMIT_ISSUER", "gpt-dashboard-portal")
    monkeypatch.setattr(config, "CONVERSATION_LOAD_PERMIT_AUDIENCE", "chat-app")
    monkeypatch.setattr(config, "CONVERSATION_LOAD_PERMIT_ALLOWED_KIDS", [])

    now = int(time.time())
    payload = {
        "iss": config.CONVERSATION_LOAD_PERMIT_ISSUER,
        "aud": config.CONVERSATION_LOAD_PERMIT_AUDIENCE,
        "iat": now,
        "exp": now + 60,
        "conversation_id": 123,
        "user_email": "user@example.com",
        "sub": "other@example.com",
    }
    token = _sign_permit(private_pem=private_pem, payload=payload)

    with pytest.raises(ConversationLoadPermitError):
        verify_conversation_load_permit(token)
