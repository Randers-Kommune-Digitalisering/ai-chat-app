from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import date, datetime

Base = declarative_base()


def _to_iso(value):
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


class Conversation(Base):
    __tablename__ = 'conversations'

    id = Column(Integer, primary_key=True, autoincrement=True)
    is_active = Column(Boolean, default=True)

    title = Column(String, nullable=False)
    gpt_id = Column(String, nullable=False)
    user_email = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    thread_id = Column(String, unique=True, nullable=True)

    messages = relationship("Message", back_populates="conversation", order_by="Message.id")

    def to_dict(self, include_messages: bool = False) -> dict:
        data = {
            "id": self.id,
            "is_active": self.is_active,
            "title": self.title,
            "gpt_id": self.gpt_id,
            "user_email": self.user_email,
            "created_at": _to_iso(self.created_at),
            "updated_at": _to_iso(self.updated_at),
            "thread_id": self.thread_id,
        }

        if include_messages:
            # NOTE: Do not include Message.conversation to avoid circular references.
            data["messages"] = [m.to_dict() for m in (self.messages or [])]

        return data


class Message(Base):
    __tablename__ = 'messages'

    id = Column(Integer, primary_key=True, autoincrement=True)

    conversation_id = Column(Integer, ForeignKey('conversations.id'), nullable=False)
    sender = Column(String, nullable=False)
    content = Column(String, nullable=False)
    time_spent = Column(Integer, nullable=True)
    timestamp = Column(DateTime, nullable=False)

    conversation = relationship("Conversation", back_populates="messages")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "sender": self.sender,
            "content": self.content,
            "timestamp": _to_iso(self.timestamp),
            "time_spent": self.time_spent,
        }
