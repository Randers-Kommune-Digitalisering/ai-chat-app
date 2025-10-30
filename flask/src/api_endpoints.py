import logging
from flask import Blueprint, jsonify, request
from utils.azure_openai import get_chat_client

logger = logging.getLogger(__name__)
api_endpoints = Blueprint('api', __name__, url_prefix='/api')
azure_client = get_chat_client()


@api_endpoints.route('/threads', methods=['POST'])
def create_thread():
    thread_id = azure_client.create_thread()
    return jsonify({"success": True, "message": "Thread created successfully", "thread_id": thread_id})


@api_endpoints.route('/threads/<thread_id>/messages', methods=['POST'])
def create_message(thread_id):
    message = request.json.get("message")
    files = request.files.getlist("files")
    if not thread_id:
        return jsonify({"success": False, "message": "thread_id is required"}), 400
    if not message:
        return jsonify({"success": False, "message": "Message is required"}), 400

    response, refs = azure_client.fetch_chat_response(thread_id, message, files)
    if not response:
        return jsonify({"success": False, "message": "Failed to fetch response from Azure"}), 500

    return jsonify({"success": True, "response": response, "references": refs})
