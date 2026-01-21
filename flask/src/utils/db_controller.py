from utils.config import POSTGRES_USER, POSTGRES_PASS, POSTGRES_HOST, POSTGRES_DB
from utils.database import DatabaseClient
from models import Conversation
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


def create_conversation(session, user_email, title):
    try:
        new_conversation = Conversation(
            user_email=user_email,
            title=title,
            is_active=True
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


def add_message_to_conversation(session, conversation_id, message_content, sender, file_content=None):
    try:
        conversation = session.query(Conversation).filter(
            Conversation.id == conversation_id,
            Conversation.is_active
        ).first()
        if conversation:
            conversation.messages.append({
                'content': message_content,
                'sender': sender
            })
            session.commit()
            return True
        return False
    except Exception as e:
        logger.error(f"Error adding message to conversation {conversation_id}: {e}")
        session.rollback()
        return False
