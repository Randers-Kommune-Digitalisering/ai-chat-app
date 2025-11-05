import requests

from utils.config import ASSISTANT_NAME, FEEDBACK_MAIL_API_RECIPIENT, FEEDBACK_MAIL_API_SENDER, FEEDBACK_MAIL_API_URL


def send_mail(body: str) -> requests.Response:
    payload = {
        "from": FEEDBACK_MAIL_API_SENDER,
        "to": FEEDBACK_MAIL_API_RECIPIENT,
        "title": f"{ASSISTANT_NAME} - Feedback fra bruger",
        "body": body
    }
    response = requests.post(FEEDBACK_MAIL_API_URL, json=payload)
    response.raise_for_status()
    return response


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


def send_user_feedback(feedback: str, response_index: str, chat_history: list) -> requests.Response:
    mail_body = create_feedback_mail(feedback, response_index, chat_history)
    try:
        response = send_mail(mail_body)
        data = response.json()
    except requests.RequestException as e:
        print(f"Error sending feedback email: {e}")
        return None
    except ValueError:
        return None
    return data
