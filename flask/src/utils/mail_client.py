import logging

from rkdigi import EmailSender

from utils.config import (
    ASSISTANT_NAME,
    FEEDBACK_MAIL_RECIPIENT,
    FEEDBACK_SMTP_PORT,
    FEEDBACK_SMTP_SENDER_EMAIL,
    FEEDBACK_SMTP_SENDER_NAME,
    FEEDBACK_SMTP_SENDER_PASSWORD,
    FEEDBACK_SMTP_SERVER,
)

logger = logging.getLogger(__name__)


def _build_sender() -> str | tuple[str, str]:
    if FEEDBACK_SMTP_SENDER_NAME and FEEDBACK_SMTP_SENDER_EMAIL:
        return (FEEDBACK_SMTP_SENDER_NAME, FEEDBACK_SMTP_SENDER_EMAIL)
    return FEEDBACK_SMTP_SENDER_EMAIL


def send_mail(body: str) -> None:
    if not FEEDBACK_SMTP_SERVER:
        raise RuntimeError("FEEDBACK_SMTP_SERVER is not configured")

    if not FEEDBACK_MAIL_RECIPIENT:
        raise RuntimeError("FEEDBACK_MAIL_RECIPIENT is not configured")

    email_sender = EmailSender(
        smtp_server=FEEDBACK_SMTP_SERVER,
        smtp_port=FEEDBACK_SMTP_PORT,
        sender_email=FEEDBACK_SMTP_SENDER_EMAIL or None,
        sender_password=FEEDBACK_SMTP_SENDER_PASSWORD or None,
        sender_name=FEEDBACK_SMTP_SENDER_NAME or None,
    )

    email_sender.send_email(
        sender=_build_sender() or '',
        recipients=FEEDBACK_MAIL_RECIPIENT,
        subject=f"{ASSISTANT_NAME} - Feedback fra bruger",
        body=body,
    )


def create_feedback_mail(feedback: str, response_index: str, chat_history: list) -> str:
    try:
        index = int(response_index.split("_")[1]) + 1  # Extract index from 'msg_0', make it 1-based
    except (IndexError, ValueError):
        index = response_index  # Fallback to raw value if parsing fails
    mail_body = f"Feedback fra bruger modtaget:\n\n`{feedback}`\n"
    mail_body += f"\nFeedback er vedr. svar #{index}\n"
    mail_body += "\nFuld chathistorik:\n\n"
    for idx, message in enumerate(chat_history):
        mail_body += f"#{idx + 1}: {message['content']}\n"
    return mail_body


def send_user_feedback(feedback: str, response_index: str, chat_history: list) -> dict | None:
    mail_body = create_feedback_mail(feedback, response_index, chat_history)
    try:
        send_mail(mail_body)
    except Exception as e:
        logger.error(f"Error sending feedback email: {e}", exc_info=True)
        return None
    return {"sent": True}
