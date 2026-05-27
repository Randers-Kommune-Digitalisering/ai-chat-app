import base64
import json
from dataclasses import dataclass
from typing import Any
from authlib.jose import JsonWebToken
from authlib.jose.errors import JoseError

import utils.config as config


@dataclass(frozen=True)
class ConversationLoadPermit:
    conversation_id: int
    user_email: str
    claims: dict[str, Any]


class ConversationLoadPermitError(ValueError):
    """Raised when a conversation load permit is missing/invalid."""


def _normalize_pem(pem: str) -> str:
    """
    Normalize a PEM string by stripping whitespace and replacing literal "\n" with actual newlines.
    """
    # Support env vars where newlines are encoded as literal "\\n".
    return (pem or "").strip().replace("\\n", "\n")


def _b64url_decode(segment: str) -> bytes:
    """
    Decode a base64url-encoded string, adding necessary padding.
    """
    if not isinstance(segment, str) or not segment:
        raise ConversationLoadPermitError("Invalid JWT header")
    padding = "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(segment + padding)
    except Exception as exc:
        raise ConversationLoadPermitError("Invalid JWT header") from exc


def _decode_jwt_header(token: str) -> dict[str, Any]:
    """
    Decode the header of a JWT token.

    :param token: The JWT token.
    :return: The decoded JWT header.

    :raises ConversationLoadPermitError: If the JWT header is invalid.
    """
    try:
        header_segment = (token or "").split(".", 2)[0]
        raw = _b64url_decode(segment=header_segment)
        header = json.loads(raw.decode("utf-8"))
        if not isinstance(header, dict):
            raise ConversationLoadPermitError("Invalid JWT header")
        return header
    except ConversationLoadPermitError:
        raise
    except Exception as exc:
        raise ConversationLoadPermitError("Invalid JWT header") from exc


def verify_conversation_load_permit(token: str) -> ConversationLoadPermit:
    """
    Verify and decode a portal-issued conversation load permit.

    Requirements:
    - RS256 signature
    - Valid `iss`, `aud`, `exp`
    - Required claims: `conversation_id` (int), `user_email` (non-empty str)
    - Optional: enforce `kid` allowlist

    :param token: The JWT conversation load permit issued by the portal.
    :return: A ConversationLoadPermit object containing the conversation_id, user_email, and all claims.

    :raises ConversationLoadPermitError: If the permit is missing, invalid, expired, or fails any verification checks.
    """

    if not token or not isinstance(token, str):
        raise ConversationLoadPermitError("Missing permit")

    public_key_pem = _normalize_pem(pem=config.CONVERSATION_LOAD_PERMIT_RS_PUBLIC_KEY_PEM)

    if not public_key_pem:
        raise ConversationLoadPermitError("Permit verification is not configured")

    header = _decode_jwt_header(token=token)
    if header.get("alg") != "RS256":
        raise ConversationLoadPermitError("Unsupported permit algorithm")

    if config.CONVERSATION_LOAD_PERMIT_ALLOWED_KIDS:
        kid = header.get("kid")
        if not kid or kid not in config.CONVERSATION_LOAD_PERMIT_ALLOWED_KIDS:
            raise ConversationLoadPermitError("Untrusted permit key")

    claims_options = {
        "iss": {"essential": True, "value": config.CONVERSATION_LOAD_PERMIT_ISSUER},
        "aud": {"essential": True, "value": config.CONVERSATION_LOAD_PERMIT_AUDIENCE},
        "exp": {"essential": True},
    }

    try:
        jwt = JsonWebToken(["RS256"])
        claims = jwt.decode(token, public_key_pem, claims_options=claims_options)
        claims.validate()
    except JoseError as exc:
        raise ConversationLoadPermitError("Invalid permit") from exc
    except Exception as exc:
        raise ConversationLoadPermitError("Invalid permit") from exc

    conversation_id = claims.get("conversation_id")
    try:
        conversation_id = int(conversation_id)
    except (TypeError, ValueError) as exc:
        raise ConversationLoadPermitError("Invalid conversation_id") from exc

    user_email = claims.get("user_email")
    if not isinstance(user_email, str) or not user_email.strip():
        raise ConversationLoadPermitError("Invalid user_email")
    user_email = user_email.strip()

    sub = claims.get("sub")
    if sub is not None and isinstance(sub, str) and sub.strip():
        if sub.strip() != user_email:
            raise ConversationLoadPermitError("Permit subject mismatch")

    return ConversationLoadPermit(
        conversation_id=conversation_id,
        user_email=user_email,
        claims=dict(claims),
    )


def extract_bearer_token(authorization_header: str | None) -> str:
    """
    Extract token from an Authorization header.

    :param authorization_header: The Authorization header value.
    :return: The extracted token, or an empty string if missing/invalid.
    """
    if not authorization_header:
        return ""
    value = str(authorization_header).strip()
    if not value.lower().startswith("bearer "):
        return ""
    return value[7:].strip()
