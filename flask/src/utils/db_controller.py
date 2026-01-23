from datetime import datetime

from utils.config import (
    ASSISTANT_NAME_ID,
    POSTGRES_USER,
    POSTGRES_PASS,
    POSTGRES_HOST,
    POSTGRES_DB,
)
from utils.database import DatabaseClient
from models import Conversation, Message
import logging


logger = logging.getLogger(__name__)


def get_db_client():
    return DatabaseClient(
        db_type='postgresql',
        database=POSTGRES_DB,
        username=POSTGRES_USER,
        password=POSTGRES_PASS,
        host=POSTGRES_HOST,
        port='5432'
    )


def get_user_conversation(session, user_email, conversation_id):
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


def create_conversation(session, user_email, title, thread_id=None):
    try:
        now = datetime.utcnow()
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


def deactivate_conversation(session, user_email, conversation_id):
    try:
        conversation = get_user_conversation(session, user_email, conversation_id)
        if conversation:
            conversation.is_active = False
            session.commit()
            return True
        return False
    except Exception as e:
        logger.error(f"Error deactivating conversation {conversation_id} for user {user_email}: {e}")
        session.rollback()
        return False


def add_message_to_conversation(session, conversation_id, message_content, sender, references=[], file_content=None):
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
            now = datetime.utcnow()
            message = Message(
                conversation_id=conversation.id,
                sender=sender,
                content=message_content,
                timestamp=now
            )
            conversation.updated_at = now
            conversation.messages.append(message)
            session.commit()
            return True
        return False
    except Exception as e:
        logger.error(f"Error adding message to conversation {conversation_id}: {e}")
        session.rollback()
        return False
