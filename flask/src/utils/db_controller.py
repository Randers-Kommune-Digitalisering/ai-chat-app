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
            Conversation.is_active == True
        ).first()
        return conversation
    except Exception as e:
        logger.error(f"Error fetching conversation {conversation_id} for user {user_email}: {e}")
        return None
