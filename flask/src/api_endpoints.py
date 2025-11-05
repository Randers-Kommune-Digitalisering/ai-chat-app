import logging
from flask import Blueprint, jsonify, request
import base64
import io
from utils.azure_openai import get_chat_client

# Suppress Azure SDK and HTTP logging
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
api_endpoints = Blueprint('api', __name__, url_prefix='/api')
azure_client = get_chat_client()


@api_endpoints.route('/threads', methods=['POST'])
def create_thread():
    thread_id = azure_client.create_thread()
    return jsonify({"success": True, "message": "Thread created successfully", "thread_id": thread_id})


@api_endpoints.route('/threads/<thread_id>/messages', methods=['POST'])
def create_thread_message(thread_id):
    message = request.json.get("message")
    files_data = request.json.get("files", [])
    if not thread_id:
        return jsonify({"success": False, "message": "thread_id is required"}), 400
    if not message:
        return jsonify({"success": False, "message": "Message is required"}), 400

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

    response, refs = azure_client.fetch_chat_response(message, files, thread_id)
    if not response:
        return jsonify({"success": False, "message": "Failed to fetch response from Azure"}), 500

    return jsonify({"success": True, "response": response, "references": refs})


@api_endpoints.route('/chat/messages', methods=['POST'])
def create_chat_message():
    messages = request.json.get("messages", [])
    if not messages:
        return jsonify({"success": False, "message": "Messages are required"}), 400

    # Parse files from JSON: each file is { name, content (base64) }
    for msg in messages:
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

    response, refs = azure_client.fetch_chat_response(messages)
    if not response:
        return jsonify({"success": False, "message": "Failed to fetch response from Azure"}), 500

    return jsonify({"success": True, "response": response, "references": refs})
