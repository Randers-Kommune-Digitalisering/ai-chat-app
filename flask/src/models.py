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
    timestamp = Column(DateTime, nullable=False)

    conversation = relationship("Conversation", back_populates="messages")
    attachments = relationship("Attachment", back_populates="message", order_by="Attachment.id")
    references = relationship("Reference", back_populates="message", order_by="Reference.id")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "sender": self.sender,
            "content": self.content,
            "timestamp": _to_iso(self.timestamp),
            "attachments": [att.to_dict() for att in getattr(self, 'attachments', [])],
            "references": [ref.to_dict() for ref in getattr(self, 'references', [])]
        }


class Attachment(Base):
    __tablename__ = 'attachments'

    id = Column(Integer, primary_key=True, autoincrement=True)

    message_id = Column(Integer, ForeignKey('messages.id'), nullable=False)
    file_name = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    file_content = Column(String, nullable=False)  # Base64 encoded content

    message = relationship("Message", back_populates="attachments")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "message_id": self.message_id,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "file_content": self.file_content,
        }


class Reference(Base):
    __tablename__ = 'references'

    id = Column(Integer, primary_key=True, autoincrement=True)

    message_id = Column(Integer, ForeignKey('messages.id'), nullable=False)
    reference_type = Column(String, nullable=False)
    reference_content = Column(String, nullable=False)

    message = relationship("Message", back_populates="references")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "message_id": self.message_id,
            "reference_type": self.reference_type,
            "reference_content": self.reference_content
        }
