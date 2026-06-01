from datetime import datetime, timezone
import base64
import json
import mimetypes
from typing import Any, Mapping, Sequence, TypeAlias

import sqlalchemy

from utils.config import (
    ASSISTANT_NAME_ID,
    POSTGRES_USER,
    POSTGRES_PASS,
    POSTGRES_HOST,
    POSTGRES_DB,
    POSTGRES_PORT,
)
from utils.database import DatabaseClient
from utils.file_types import UploadedFile
from models import Conversation, Message, Attachment, Reference
import logging

logger = logging.getLogger(__name__)

FileContentItem: TypeAlias = Mapping[str, Any] | UploadedFile
FileContentArg: TypeAlias = Sequence[FileContentItem] | FileContentItem | None

ReferenceItem: TypeAlias = Mapping[str, Any] | str
ReferencesArg: TypeAlias = Sequence[ReferenceItem] | ReferenceItem | None


def _utcnow_naive() -> datetime:
    """
    Returns the current UTC time as a naive datetime.

    The DB columns for timestamps are modeled as SQLAlchemy DateTime without
    timezone support (i.e. PostgreSQL `timestamp without time zone`). psycopg2
    and/or SQLAlchemy can reject offset-aware datetimes for those columns.

    :return: Current UTC time as a naive datetime.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_db_client() -> DatabaseClient:
    """
    Initialize and return a DatabaseClient instance for PostgreSQL.

    :return: A DatabaseClient instance configured for PostgreSQL.
    """
    return DatabaseClient(
        db_type='postgresql',
        database=POSTGRES_DB,
        username=POSTGRES_USER,
        password=POSTGRES_PASS,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT
    )


def get_user_conversation(session: sqlalchemy.orm.Session, user_email: str, conversation_id: int) -> Conversation | None:
    """
    Fetch a user's conversation by ID.

    :param session: The SQLAlchemy session to use for the query.
    :param user_email: The email of the user.
    :param conversation_id: The ID of the conversation.
    :return: The conversation if found, otherwise None.
    """
    try:
        conversation = session.query(Conversation).filter(
            Conversation.id == conversation_id,
            Conversation.user_email == user_email,
            Conversation.is_active
        ).first()
        if conversation and conversation.messages:
            # Ensure deterministic ordering (oldest -> newest) based on Message.id
            conversation.messages.sort(key=lambda m: getattr(m, 'id', None) or (m.get('id') if isinstance(m, dict) else 0))
        return conversation
    except Exception as e:
        logger.error(f"Error fetching conversation {conversation_id} for user {user_email}: {e}")
        return None


def create_conversation(session: sqlalchemy.orm.Session, user_email: str, title: str, thread_id: str | None = None) -> Conversation | None:
    """
    Create a new conversation for a user.

    :param session: The SQLAlchemy session to use for the operation.
    :param user_email: The email of the user.
    :param title: The title of the conversation.
    :param thread_id: Optional thread ID for the conversation.
    :return: The newly created conversation if successful, otherwise None.
    """
    try:
        now = _utcnow_naive()
        new_conversation = Conversation(
            user_email=user_email,
            title=title,
            is_active=True,
            gpt_id=(ASSISTANT_NAME_ID),
            created_at=now,
            updated_at=now,
            thread_id=thread_id,
        )
        session.add(new_conversation)
        session.commit()
        return new_conversation
    except Exception as e:
        logger.error(f"Error creating conversation for user {user_email}: {e}")
        session.rollback()
        return None


def add_message_to_conversation(
    session: sqlalchemy.orm.Session,
    conversation_id: int,
    message_content: str,
    sender: str,
    references: ReferencesArg = None,
    file_content: FileContentArg = None,
) -> bool:
    """
    Add a message to a conversation.

    :param session: The SQLAlchemy session to use for the operation.
    :param conversation_id: The ID of the conversation.
    :param message_content: The content of the message.
    :param sender: The sender of the message.
    :param references: Optional reference payload(s) associated with the message.
        Accepted shapes:
        - dict payloads (e.g. Azure citation dicts)
        - strings (stored as-is)
        - a single item or a list/tuple of items
    :param file_content: Optional attachment payload(s) associated with the message.
        Accepted shapes:
        - file-like objects with `.read()` and `.filename` (e.g. io.BytesIO with `.filename` attached)
        - dict payloads with file metadata/content (e.g. {name/content} or {file_name/file_content})
        - a single item or a list/tuple of items
    :return: True if the message was added successfully, otherwise False.
    """
    try:
        try:
            conversation_id = int(conversation_id)
        except (TypeError, ValueError):
            logger.error(f"Invalid conversation_id for add_message_to_conversation: {conversation_id!r}")
            return False

        conversation = session.query(Conversation).filter(
            Conversation.id == conversation_id,
            Conversation.is_active
        ).first()

        if conversation:
            now = _utcnow_naive()
            message = Message(
                conversation_id=conversation.id,
                sender=sender,
                content=message_content,
                timestamp=now
            )
            conversation.updated_at = now
            conversation.messages.append(message)

            # Ensure message.id is generated before we create related rows.
            # Without this, message.id can be None until commit, causing NOT NULL
            # violations for Attachment/Reference.message_id.
            session.flush()

            def _normalize_file_item(item: Any) -> dict[str, Any] | None:
                """
                Return normalized attachment dict or None.

                Supports:
                - file-like objects (e.g., io.BytesIO) with a .filename attribute
                - dicts with file metadata/content

                :param item: The raw file item, which can be a dict or file-like object.
                :return: A dict with 'file_name', 'file_type', 'file_size', and 'file_content' (base64 string), or None if input is invalid.
                """
                if item is None:
                    return None

                # Dict shape
                if isinstance(item, dict):
                    file_name = item.get("file_name") or item.get("name") or item.get("filename") or "unknown"
                    file_type = item.get("file_type") or mimetypes.guess_type(file_name)[0] or "application/octet-stream"

                    raw_content = item.get("file_content")
                    if raw_content is None:
                        raw_content = item.get("content")

                    # Accept either raw bytes or base64 string
                    if isinstance(raw_content, (bytes, bytearray)):
                        content_b64 = base64.b64encode(bytes(raw_content)).decode("ascii")
                        file_size = item.get("file_size") or len(raw_content)
                    elif isinstance(raw_content, str):
                        content_b64 = raw_content
                        file_size = item.get("file_size") or 0
                    else:
                        content_b64 = ""
                        file_size = item.get("file_size") or 0

                    return {
                        "file_name": file_name,
                        "file_type": file_type,
                        "file_size": int(file_size) if file_size is not None else 0,
                        "file_content": content_b64,
                    }

                # File-like shape
                file_name = getattr(item, "filename", None) or getattr(item, "name", None) or "unknown"
                file_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"

                data = b""
                if hasattr(item, "getvalue"):
                    data = item.getvalue() or b""
                elif hasattr(item, "read"):
                    try:
                        # Try not to disturb caller's current position
                        pos = item.tell() if hasattr(item, "tell") else None
                        if hasattr(item, "seek"):
                            item.seek(0)
                        data = item.read() or b""
                        if pos is not None and hasattr(item, "seek"):
                            item.seek(pos)
                    except Exception:
                        data = b""

                return {
                    "file_name": file_name,
                    "file_type": file_type,
                    "file_size": len(data),
                    "file_content": base64.b64encode(data).decode("ascii") if data else "",
                }

            def _normalize_reference_item(item: Any) -> dict[str, Any] | None:
                """
                Return normalized reference dict or None.

                Azure clients currently return citation dicts like:
                - Chat: { url, title, refs }
                - Agent: { url, title, refs, replace_refs? }

                :param item: The raw reference item, which can be a dict or other type.
                :return: A dict with 'reference_type' and 'reference_content', or None if input is invalid.
                """
                if not item:
                    return None
                if isinstance(item, dict):
                    if "reference_type" in item or "reference_content" in item:
                        return {
                            "reference_type": item.get("reference_type") or "unknown",
                            "reference_content": item.get("reference_content") or "",
                        }

                    # Default: store the entire citation payload as JSON
                    reference_type = "citation"
                    if "url" in item:
                        reference_type = "url"
                    try:
                        content = json.dumps(item, ensure_ascii=False)
                    except Exception:
                        content = str(item)
                    return {
                        "reference_type": reference_type,
                        "reference_content": content,
                    }

                # Non-dict reference: store string representation
                return {
                    "reference_type": "unknown",
                    "reference_content": str(item),
                }

            # Insert attachments (user uploaded files)
            if file_content:
                for fc in file_content if isinstance(file_content, (list, tuple)) else [file_content]:
                    normalized = _normalize_file_item(item=fc)
                    if not normalized:
                        continue
                    session.add(
                        Attachment(
                            message_id=message.id,
                            file_name=normalized["file_name"],
                            file_type=normalized["file_type"],
                            file_size=normalized["file_size"],
                            file_content=normalized["file_content"],
                        )
                    )

            # Insert references (assistant citations)
            if references:
                for ref in references if isinstance(references, (list, tuple)) else [references]:
                    normalized = _normalize_reference_item(item=ref)
                    if not normalized:
                        continue
                    session.add(
                        Reference(
                            message_id=message.id,
                            reference_type=normalized["reference_type"],
                            reference_content=normalized["reference_content"],
                        )
                    )

            session.commit()

            return True
        return False

    except Exception as e:
        logger.error(f"Error adding message to conversation {conversation_id}: {e}")
        session.rollback()
        return False
