import logging
from flask import Blueprint, jsonify
from utils.azure_openai import get_chat_client

logger = logging.getLogger(__name__)
api_endpoints = Blueprint('api', __name__, url_prefix='/api')
azure_client = get_chat_client()


@api_endpoints.route('/threads', methods=['POST'])
def create_thread():
    return jsonify({"success": True, "message": "Thread created successfully"})

@api_endpoints.route('/threads/<thread_id>/messages', methods=['POST'])
def create_message(thread_id):
    return jsonify({"success": True, "message": "Message sent successfully", "thread_id": thread_id})
