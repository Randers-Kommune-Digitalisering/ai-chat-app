import logging
from flask import Blueprint, jsonify, request
import base64
import io
from utils.azure_openai import get_chat_client
from utils.config import ASSISTANT_TYPE, ASSISTANT_NAME, PREDEFINED_QUESTIONS, SHOW_ASSISTANT_TOGGLE, ASSISTANT_DESCRIPTION
from utils.mail_client import send_user_feedback
from utils.input_filter import redact_content, get_filter_content
from utils.logging import chat_messages_counter, chat_feedback_counter, metrics_base_labels

# Suppress Azure SDK and HTTP logging
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
api_endpoints = Blueprint('api', __name__, url_prefix='/api')
azure_client = get_chat_client()


# Config endpoint for frontend
@api_endpoints.route('/config', methods=['GET'])
def get_config():
    config = {
        "assistantName": ASSISTANT_NAME,
        "isAgent": ASSISTANT_TYPE.lower() == "agent",
        "predefinedQuestions": PREDEFINED_QUESTIONS,
        "showAssistantToggle": SHOW_ASSISTANT_TOGGLE,
        "description": ASSISTANT_DESCRIPTION
    }
    return jsonify(config)


@api_endpoints.route('/threads', methods=['POST'])
def create_thread():
    thread_id = azure_client.create_thread()
    return jsonify({"success": True, "message": "Thread created successfully", "thread_id": thread_id})


# Endpoint to handle messages in a thread (Agent mode)
@api_endpoints.route('/threads/<thread_id>/messages', methods=['POST'])
def create_thread_message(thread_id):
    message = request.json.get("message")
    files_data = request.json.get("files", [])
    use_alt = request.json.get("use_alt", False)
    if not thread_id:
        return jsonify({"success": False, "message": "thread_id is required"}), 400
    if not message:
        return jsonify({"success": False, "message": "Message is required"}), 400

    chat_messages_counter.labels(**metrics_base_labels(), mode='agent').inc()

    # Redact sensitive content in user messages
    message = redact_content(message)

    # Parse files from JSON: each file is { name, content (base64) }
    files = []
    for file_info in files_data:
        name = file_info.get("name")
        content_b64 = file_info.get("content")
        if not name or not content_b64:
            continue
        try:
            file_bytes = base64.b64decode(content_b64)
            file_obj = io.BytesIO(file_bytes)
            file_obj.filename = name  # For extract_text_from_file
            files.append(file_obj)
        except Exception as e:
            logger.warning(f"Failed to decode file {name}: {e}")
    try:
        response, refs = azure_client.fetch_chat_response(message, files, thread_id, use_alt=use_alt)
        if not response:
            return jsonify({"success": False, "message": "Failed to fetch response from Azure"}), 500
    except Exception as e:
        logger.error(f"Error fetching chat response: {e}")
        return jsonify({"success": False, "message": "Error fetching chat response", "error": str(e)}), 500

    return jsonify({"success": True, "response": response, "references": refs})


# Endpoint to handle chat messages (Chat mode)
@api_endpoints.route('/chat/messages', methods=['POST'])
def create_chat_message():
    messages = request.json.get("messages", [])
    if not messages:
        return jsonify({"success": False, "message": "Messages are required"}), 400

    # Count as a single user message (frontend sends full history).
    chat_messages_counter.labels(**metrics_base_labels(), mode='chat').inc()

    for msg in messages:
        # Redact sensitive content in user messages
        msg["content"] = redact_content(msg.get("content", ""))

        # Parse files from JSON: each file is { name, content (base64) }
        new_files = []
        for file_info in msg.get("files", []):
            name = file_info.get("name")
            content_b64 = file_info.get("content")
            if not name or not content_b64:
                continue
            try:
                file_bytes = base64.b64decode(content_b64)
                file_obj = io.BytesIO(file_bytes)
                file_obj.filename = name  # For extract_text_from_file
                new_files.append(file_obj)
            except Exception as e:
                logger.warning(f"Failed to decode file {name}: {e}")
        msg["files"] = new_files

    try:
        response, refs = azure_client.fetch_chat_response(messages)
        if not response:
            return jsonify({"success": False, "message": "Failed to fetch response from Azure"}), 500
    except Exception as e:
        logger.error(f"Error fetching chat response: {e}")
        return jsonify({"success": False, "message": "Error fetching chat response", "error": str(e)}), 500

    return jsonify({"success": True, "response": response, "references": refs})


# Filter endpoint
@api_endpoints.route('/filter', methods=['POST'])
def filter_content():
    content = request.json.get("content")
    if not content:
        return jsonify({"success": False, "message": "Content is required"}), 400
    try:
        filtered_content = get_filter_content(content)
    except Exception as e:
        logger.error(f"Error filtering content: {e}")
        return jsonify({"success": False, "message": "Error filtering content", "error": str(e)}), 500
    return jsonify({"success": True, "filtered_content": filtered_content})


# Feedback endpoint
@api_endpoints.route('/feedback', methods=['POST'])
def send_feedback():
    data = request.json
    feedback = data.get('feedback')
    response_index = data.get('response_index')
    chat_history = data.get('chat_history')
    if feedback is None or response_index is None or chat_history is None:
        return jsonify({"success": False, "message": "Missing feedback, response_index, or chat_history"}), 400

    chat_feedback_counter.labels(**metrics_base_labels(), feedback_type='custom').inc()
    result = send_user_feedback(feedback, response_index, chat_history)
    if result is None:
        return jsonify({"success": False, "message": "Failed to send feedback"}), 500
    return jsonify({"success": True, "data": result})


@api_endpoints.route('/feedback/like', methods=['POST'])
def send_like_feedback():
    chat_feedback_counter.labels(**metrics_base_labels(), feedback_type='like').inc()
    return jsonify({"success": True})
