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


def _ensure_randers_domain(email: str | None) -> str | None:
    """
    Ensures that the given email has a domain. If the email is missing a domain, "@randers.dk" will be appended.

    :param email: The email address to check and modify if necessary.
    :return: The modified email address with "@randers.dk" appended if it was missing a domain, or the original email if it already had a domain.
    """
    if not email:
        return email

    cleaned = email.strip()
    if not cleaned:
        return cleaned

    if "@" not in cleaned:
        return f"{cleaned}@randers.dk"

    local, domain = cleaned.split("@", 1)
    if local and not domain:
        return f"{local}@randers.dk"

    return cleaned


def _build_sender() -> str | tuple[str, str]:
    """
    Builds the sender information for the email.

    :return: A tuple of (sender_name, sender_email) if both are available, otherwise just the sender_email.
    """
    sender_email = _ensure_randers_domain(FEEDBACK_SMTP_SENDER_EMAIL)
    if FEEDBACK_SMTP_SENDER_NAME and sender_email:
        return (FEEDBACK_SMTP_SENDER_NAME, sender_email)
    return sender_email


def _build_recipients() -> list[str]:
    recipients: list[str] = []
    for recipient in FEEDBACK_MAIL_RECIPIENT:
        normalized = _ensure_randers_domain(recipient)
        if normalized:
            recipients.append(normalized)
    return recipients


def send_mail(body: str) -> None:
    """
    Sends an email with the given body to the configured recipients using the SMTP server settings.

    :param body: The body of the email to be sent.
    :raises RuntimeError: If the SMTP server or mail recipient configuration is missing.
    :raises Exception: If there is an error sending the email.
    """
    if not FEEDBACK_SMTP_SERVER:
        raise RuntimeError("FEEDBACK_SMTP_SERVER is not configured")

    recipients = _build_recipients()
    if not recipients:
        raise RuntimeError("FEEDBACK_MAIL_RECIPIENT is not configured")

    sender_email = _ensure_randers_domain(FEEDBACK_SMTP_SENDER_EMAIL)
    email_sender = EmailSender(
        smtp_server=FEEDBACK_SMTP_SERVER,
        smtp_port=FEEDBACK_SMTP_PORT,
        sender_email=sender_email or None,
        sender_password=FEEDBACK_SMTP_SENDER_PASSWORD or None,
        sender_name=FEEDBACK_SMTP_SENDER_NAME or None,
    )

    email_sender.send_email(
        sender=_build_sender() or '',
        recipients=recipients,
        subject=f"{ASSISTANT_NAME} - Feedback fra bruger",
        body=body,
    )


def create_feedback_mail(feedback: str, response_index: str, chat_history: list) -> str:
    """
    Creates the body of the feedback email.

    :param feedback: The feedback provided by the user.
    :param response_index: The index of the response the feedback is related to.
    :param chat_history: The chat history leading up to the feedback.
    :return: The formatted email body as a string.
    """
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
    """
    Sends user feedback via email.

    :param feedback: The feedback provided by the user.
    :param response_index: The index of the response the feedback is related to.
    :param chat_history: The chat history leading up to the feedback.
    :return: A dictionary indicating the feedback was sent, or None if there was an error.
    """
    mail_body = create_feedback_mail(feedback, response_index, chat_history)
    try:
        send_mail(mail_body)
    except Exception as e:
        logger.error(f"Error sending feedback email: {e}", exc_info=True)
        return None
    return {"sent": True}
