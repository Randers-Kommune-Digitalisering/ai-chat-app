import logging
import threading
import atexit
from flask import Blueprint, jsonify, request
import base64
import io
from utils.azure_openai import get_chat_client, get_title_generator
from utils.config import ASSISTANT_TYPE, ASSISTANT_NAME, ASSISTANT_NAME_ID, PREDEFINED_QUESTIONS, SHOW_ASSISTANT_TOGGLE, ASSISTANT_DESCRIPTION, ALT_TOGGLE_LABEL, ALT_ALERT_MSG, ALT_ALERT_TYPE, USE_DB
from utils.mail_client import send_user_feedback
from utils.input_filter import redact_content, get_filter_content
from utils.logging import chat_messages_counter, chat_feedback_counter, chat_conversations_counter, metrics_base_labels
from utils.db_controller import (
    get_db_client,
    get_user_conversation,
    create_conversation as create_db_conversation,
    add_message_to_conversation
)
from utils.conversation_permits import (
    ConversationLoadPermitError,
    extract_bearer_token,
    verify_conversation_load_permit,
)

# Suppress Azure SDK and HTTP logging
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
api_endpoints = Blueprint('api', __name__, url_prefix='/api')
azure_client = get_chat_client()
db_client = get_db_client()


# add doc strings
def _close_azure_client() -> None:
    try:
        close_fn = getattr(azure_client, "close", None)
        if callable(close_fn):
            close_fn()
    except Exception:
        pass


atexit.register(_close_azure_client)


def _start_title_generation_thread(*, first_user_message: str):
    """Start generating a conversation title in the background.

    Returns (thread, result_dict). Caller can join the thread later to wait
    for the title before writing the conversation to the DB.
    """

    result = {"title": None}

    def _worker() -> None:
        try:
            generator = get_title_generator()
            if not generator:
                return
            title = generator.generate_title([
                {"role": "user", "content": first_user_message}
            ])
            if title:
                result["title"] = title
        except Exception as e:
            logger.warning(f"Failed to generate conversation title: {e}")

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread, result


# Config endpoint for frontend
@api_endpoints.route('/config', methods=['GET'])
def get_config():
    config = {
        "assistantName": ASSISTANT_NAME,
        "assistantNameId": ASSISTANT_NAME_ID,
        "isAgent": ASSISTANT_TYPE.lower() == "agent",
        "predefinedQuestions": PREDEFINED_QUESTIONS,
        "description": ASSISTANT_DESCRIPTION,
        "showAssistantToggle": SHOW_ASSISTANT_TOGGLE,
        "altToggleLabel": ALT_TOGGLE_LABEL,
        "altAlertMsg": ALT_ALERT_MSG,
        "altAlertType": ALT_ALERT_TYPE
    }
    return jsonify(config)


@api_endpoints.route('/threads', methods=['POST'])
def create_thread():
    try:
        thread_id = azure_client.create_thread()
        return jsonify({"success": True, "message": "Thread created successfully", "thread_id": thread_id})
    except Exception as e:
        logger.error(f"Error creating thread: {e}", exc_info=True)
        return (
            jsonify({
                "success": False,
                "message": "Assistenten havde en midlertidig fejl. Prøv igen om lidt.",
            }),
            503,
        )


# Endpoint to handle messages in a thread (Agent mode)
@api_endpoints.route('/threads/<thread_id>/messages', methods=['POST'])
def create_thread_message(thread_id):
    message = request.json.get("message")
    files_data = request.json.get("files", [])
    use_alt = request.json.get("use_alt", False)
    conversation_id = request.json.get("conversation_id")
    user_email = request.headers.get("X-User-Email") or "guest"
    if not thread_id:
        return jsonify({"success": False, "message": "Der opstod en fejl. Start en ny samtale, genindlæs siden eller prøv igen senere."}), 400
    if not message:
        return jsonify({"success": False, "message": "Der opstod en fejl. Genindlæs siden eller prøv igen senere."}), 400

    # Normalize conversation_id (frontend may send it as a string)
    if conversation_id in ("", None):
        conversation_id = None
    else:
        try:
            conversation_id = int(conversation_id)
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "Der opstod en fejl. Genindlæs siden eller prøv igen senere."}), 400

    chat_messages_counter.labels(**metrics_base_labels(), mode='agent').inc()

    # Redact sensitive content in user messages
    message = redact_content(text=message)

    title_thread = None
    title_result = None
    conversation_title = None
    if USE_DB and user_email and not conversation_id and message:
        # Generate title while we await the chat response.
        title_thread, title_result = _start_title_generation_thread(first_user_message=message)

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

    # Get response from Azure
    try:
        azure_result = azure_client.fetch_chat_response(chat_messages=message, files=files, thread_id=thread_id, use_alt=use_alt)
        if isinstance(azure_result, tuple) and len(azure_result) == 4:
            response, refs, error_message, azure_status = azure_result
        else:
            response, refs, error_message = azure_result
            azure_status = None
        if not response:
            return (
                jsonify({"success": False, "message": error_message or "Assistenten havde en midlertidig fejl. Prøv igen om lidt."}),
                int(azure_status or 500),
            )
    except Exception as e:
        logger.error(f"Error fetching chat response: {e}")
        return (
            jsonify({"success": False, "message": "Assistenten havde en midlertidig fejl. Prøv igen om lidt."}),
            503,
        )

    if not USE_DB:
        return jsonify({"success": True, "response": response, "references": refs, "conversation_id": conversation_id, "title": conversation_title})

    # Update DB (same semantics as chat mode)
    db_session = None
    try:
        db_session = db_client.get_session()

        # Create conversation if missing and we have a user
        if user_email and not conversation_id:
            if title_thread is not None:
                title_thread.join()
            generated_title = (title_result or {}).get("title") or f"Samtale {thread_id}"
            conversation_title = generated_title

            created = create_db_conversation(
                session=db_session,
                user_email=user_email,
                title=generated_title,
                thread_id=thread_id,
            )
            if created and getattr(created, "id", None) is not None:
                chat_conversations_counter.labels(**metrics_base_labels(), mode='agent').inc()
                conversation_id = int(created.id)
            else:
                logger.error("Failed to create conversation in DB")
                return jsonify({"success": True, "response": response, "references": refs, "conversation_id": conversation_id, "title": conversation_title}), 200

        # Persist messages
        if conversation_id:
            updated = add_message_to_conversation(
                session=db_session,
                conversation_id=conversation_id,
                message_content=message,
                sender='user',
                file_content=files
            )
            if not updated:
                logger.error("Failed to add user message to conversation in DB")
                return jsonify({"success": True, "response": response, "references": refs, "conversation_id": conversation_id, "title": conversation_title}), 200

            updated = add_message_to_conversation(
                session=db_session,
                conversation_id=conversation_id,
                message_content=response,
                sender='assistant',
                references=refs
            )
            if not updated:
                logger.error("Failed to add assistant message to conversation in DB")
                return jsonify({"success": True, "response": response, "references": refs, "conversation_id": conversation_id, "title": conversation_title}), 200

    except Exception as e:
        logger.error(f"Error updating conversation in DB: {e}")
        pass

    finally:
        try:
            if db_session is not None:
                db_session.close()
        except Exception:
            pass

    return jsonify({"success": True, "response": response, "references": refs, "conversation_id": conversation_id, "title": conversation_title})


# Endpoint to handle chat messages (Chat mode)
@api_endpoints.route('/chat/messages', methods=['POST'])
def create_chat_message():
    messages = request.json.get("messages", [])
    conversation_id = request.json.get("conversation_id")
    user_email = request.headers.get("X-User-Email") or "guest"
    if not messages:
        return jsonify({"success": False, "message": "Der opstod en fejl. Prøv at genindlæse siden."}), 400

    # Normalize conversation_id (frontend may send it as a string)
    if conversation_id in ("", None):
        conversation_id = None
    else:
        try:
            conversation_id = int(conversation_id)
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "Der opstod en fejl. Prøv at genindlæse siden."}), 400

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

    title_thread = None
    title_result = None
    conversation_title = None
    if USE_DB and user_email and not conversation_id and messages:
        first_user_message = next(
            (m.get("content", "") for m in messages if m.get("role") == "user"),
            ""
        )
        if first_user_message:
            # Generate title while we await the chat response.
            title_thread, title_result = _start_title_generation_thread(first_user_message=first_user_message)

    # Get response from Azure
    try:
        azure_result = azure_client.fetch_chat_response(messages)
        if isinstance(azure_result, tuple) and len(azure_result) == 4:
            response, refs, error_message, azure_status = azure_result
        else:
            response, refs, error_message = azure_result
            azure_status = None
        if not response:
            return (
                jsonify({"success": False, "message": error_message or "Assistenten havde en midlertidig fejl. Prøv igen om lidt."}),
                int(azure_status or 500),
            )
    except Exception as e:
        logger.error(f"Error fetching chat response: {e}")
        return (
            jsonify({"success": False, "message": "Assistenten havde en midlertidig fejl. Prøv igen om lidt."}),
            503,
        )

    if not USE_DB:
        return jsonify({"success": True, "response": response, "references": refs, "conversation_id": conversation_id, "title": conversation_title})

    # Update DB
    db_session = None
    try:
        db_session = db_client.get_session()

        # Create conversation in DB if conversation id is not provided
        if user_email and not conversation_id:
            if title_thread is not None:
                title_thread.join()
            generated_title = (title_result or {}).get("title") or "Ny samtale"
            conversation_title = generated_title

            created = create_db_conversation(
                session=db_session,
                user_email=user_email,
                title=generated_title
            )
            if created and getattr(created, "id", None) is not None:
                chat_conversations_counter.labels(**metrics_base_labels(), mode='chat').inc()
                conversation_id = int(created.id)
            else:
                logger.error("Failed to create conversation in DB")
                return jsonify({"success": True, "response": response, "references": refs, "conversation_id": conversation_id, "title": conversation_title})

        # Add the latest user message + assistant response to the conversation in DB
        if conversation_id:
            updated = add_message_to_conversation(
                session=db_session,
                conversation_id=conversation_id,
                message_content=messages[-1]["content"],
                sender='user',
                file_content=messages[-1].get("files")
            )
            if not updated:
                logger.error("Failed to add user message to conversation in DB")
                return jsonify({"success": True, "response": response, "references": refs, "conversation_id": conversation_id, "title": conversation_title})

            updated = add_message_to_conversation(
                session=db_session,
                conversation_id=conversation_id,
                message_content=response,
                sender='assistant',
                references=refs
            )
            if not updated:
                logger.error("Failed to add assistant message to conversation in DB")
                return jsonify({"success": True, "response": response, "references": refs, "conversation_id": conversation_id, "title": conversation_title})

    except Exception as e:
        logger.error(f"Error updating conversation in DB: {e}")
        pass

    finally:
        try:
            if db_session is not None:
                db_session.close()
        except Exception:
            pass

    return jsonify({"success": True, "response": response, "references": refs, "conversation_id": conversation_id, "title": conversation_title})


@api_endpoints.route('/conversations/<id>', methods=['GET'])
def load_conversation(id):
    # Legacy endpoint disabled: the portal must send a short-lived signed permit instead.
    # Do not accept guessed conversation IDs or X-User-Email headers for loading.
    return (
        jsonify({
            "success": False,
            "message": "Legacy endpoint disabled. Use POST /api/conversations/load with a permit.",
        }),
        410,
    )


@api_endpoints.route('/conversations/load', methods=['POST'])
def load_conversation_by_permit():
    """Load a conversation using a portal-issued RS256 load permit.

    Accepts the permit via:
    - Authorization: Bearer <permit>
    - (Optional for local debug) JSON body {"permit": "..."}

    Ignores X-User-Email entirely.
    """
    try:
        token = extract_bearer_token(request.headers.get('Authorization'))
        if not token:
            data = request.get_json(silent=True) or {}
            token = (data.get('permit') or '').strip() if isinstance(data, dict) else ''

        permit = verify_conversation_load_permit(token=token)

        with db_client.session_scope() as session:
            conversation = get_user_conversation(session=session, user_email=permit.user_email, conversation_id=permit.conversation_id)
            if not conversation:
                return jsonify({"success": False, "message": "Kunne ikke indlæse samtalen. Prøv igen senere."}), 404
            payload = conversation.to_dict(include_messages=True)

        return jsonify({"success": True, "conversation": payload})

    except ConversationLoadPermitError as e:
        # Intentionally keep the response non-specific.
        logger.warning(f"Invalid conversation load permit: {e}")
        return jsonify({"success": False, "message": "Kunne ikke indlæse samtalen. Prøv igen senere."}), 401
    except Exception as e:
        logger.error(f"Error loading conversation by permit: {e}")
        return jsonify({"success": False, "message": "Kunne ikke indlæse samtalen. Prøv igen senere."}), 500


# Filter endpoint
@api_endpoints.route('/filter', methods=['POST'])
def filter_content():
    content = request.json.get("content")
    if not content:
        return jsonify({"success": False, "message": "Der opstod en fejl. Prøv at genindlæse siden."}), 400
    try:
        filtered_content = get_filter_content(content)
    except Exception as e:
        logger.error(f"Error filtering content: {e}")
        return jsonify({"success": False, "message": "Der opstod en fejl. Prøv at genindlæse siden."}), 500
    return jsonify({"success": True, "filtered_content": filtered_content})


# Feedback endpoint
@api_endpoints.route('/feedback', methods=['POST'])
def send_feedback():
    data = request.json
    feedback = data.get('feedback')
    response_index = data.get('response_index')
    chat_history = data.get('chat_history')
    if feedback is None or response_index is None or chat_history is None:
        return jsonify({"success": False, "message": "Der opstod en fejl, og din feedback blev ikke sendt. Prøv igen senere."}), 400

    chat_feedback_counter.labels(**metrics_base_labels(), feedback_type='custom').inc()
    result = send_user_feedback(feedback, response_index, chat_history)
    if result is None:
        return jsonify({"success": False, "message": "Der opstod en fejl, og din feedback blev ikke sendt. Prøv igen senere."}), 500
    return jsonify({"success": True, "data": result})


@api_endpoints.route('/feedback/like', methods=['POST'])
def send_like_feedback():
    chat_feedback_counter.labels(**metrics_base_labels(), feedback_type='like').inc()
    return jsonify({"success": True})
