import logging
import threading
import atexit
import json
import mimetypes
from flask import Blueprint, jsonify, request, Response, stream_with_context
import base64
import io
from utils.azure_openai2 import get_chat_client, get_title_generator, count_tokens
from utils.config import AGENT_FILE_METADATA_ONLY, AGENT_FILE_SIZE_LIMIT, ASSISTANT_TYPE, ASSISTANT_NAME, ASSISTANT_NAME_ID, CONVERSATION_LOAD_CUTOFF_DATE, PREDEFINED_QUESTIONS, SHOW_ASSISTANT_TOGGLE, ASSISTANT_DESCRIPTION, ALT_TOGGLE_LABEL, ALT_ALERT_MSG, ALT_ALERT_TYPE, MAX_TOKEN_LIMIT_MESSAGE, USE_DB, TITLE_GENERATION_JOIN_TIMEOUT_S, TITLE_GENERATION_MAX_CONCURRENCY
from utils.mail_client import send_user_feedback
from utils.input_filter import redact_content, get_filter_content
from utils.logging import chat_messages_counter, chat_feedback_counter, chat_conversations_counter, title_generation_saturation_counter, title_generation_timeout_counter, title_generation_inflight_gauge, metrics_base_labels
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
_title_generation_semaphore = threading.BoundedSemaphore(value=TITLE_GENERATION_MAX_CONCURRENCY)


def _sse_event(event_name: str, payload: dict) -> str:
    """
    Build one SSE event chunk.

    :param event_name: SSE event name.
    :param payload: JSON-serializable payload.
    :return: Formatted SSE event string.
    """
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


class FileSizeLimitError(ValueError):
    pass


def _decode_uploaded_files(files_data: list, max_size_bytes: int | None = None) -> list:
    """
    Decode base64 file payloads from request JSON into file-like objects.

    :param files_data: Request files list where each item is {name, content}.
    :return: List of in-memory file objects.
    """
    files = []
    for file_info in files_data:
        name = file_info.get("name")
        content_b64 = file_info.get("content")
        if not name or not content_b64:
            continue
        try:
            if max_size_bytes is not None and len(content_b64) > ((max_size_bytes + 2) // 3) * 4:
                raise FileSizeLimitError(name)
            file_bytes = base64.b64decode(content_b64, validate=True)
            if max_size_bytes is not None and len(file_bytes) > max_size_bytes:
                raise FileSizeLimitError(name)
            file_obj = io.BytesIO(file_bytes)
            file_obj.filename = name
            files.append(file_obj)
        except FileSizeLimitError:
            raise
        except Exception as e:
            logger.warning(f"Failed to decode file {name}: {e}")
    return files


def _agent_files_for_db(files: list) -> list:
    """Return agent attachments as metadata only when configured."""
    if not AGENT_FILE_METADATA_ONLY:
        return files

    return [
        {
            "file_name": getattr(file, "filename", None) or getattr(file, "name", None) or "unknown",
            "file_type": mimetypes.guess_type(
                getattr(file, "filename", None) or getattr(file, "name", None) or "unknown"
            )[0] or "application/octet-stream",
            "file_size": len(file.getvalue()) if hasattr(file, "getvalue") else 0,
        }
        for file in files
    ]


def _close_azure_client() -> None:
    """
    Close the Azure OpenAI client if it has a close method. This is registered to run at exit to ensure any open connections are properly closed.
    """
    try:
        close_fn = getattr(azure_client, "close", None)
        if callable(close_fn):
            close_fn()
    except Exception:
        pass


atexit.register(_close_azure_client)


def _start_title_generation_thread(*, first_user_message: str, mode: str) -> tuple[threading.Thread | None, dict]:
    """
    Start generating a conversation title in the background.

    :param first_user_message: The content of the first user message, used as input for title generation.
    :return: A tuple containing the thread object (or None if skipped) and a shared result dictionary where the generated title will be stored once ready.
    """

    result = {"title": None}

    if not _title_generation_semaphore.acquire(blocking=False):
        logger.warning(
            "Skipping title generation due to concurrency limit (max=%s)",
            TITLE_GENERATION_MAX_CONCURRENCY,
        )
        title_generation_saturation_counter.labels(**metrics_base_labels(), mode=mode).inc()
        return None, result

    def _worker() -> None:
        generator = None
        title_generation_inflight_gauge.labels(**metrics_base_labels(), mode=mode).inc()
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
        finally:
            # Ensure transport/session resources are released for each title generation call.
            try:
                close_fn = getattr(getattr(generator, "client", None), "close", None)
                if callable(close_fn):
                    close_fn()
            except Exception:
                pass
            title_generation_inflight_gauge.labels(**metrics_base_labels(), mode=mode).dec()
            _title_generation_semaphore.release()

    thread = threading.Thread(target=_worker, daemon=True)
    try:
        thread.start()
    except Exception:
        _title_generation_semaphore.release()
        raise
    return thread, result


def _resolve_title_result(*, title_thread: threading.Thread | None, title_result: dict | None, fallback_title: str, mode: str) -> str:
    """
    Resolve title generation with bounded wait. Falls back if title generation exceeds join timeout.

    :param title_thread: The thread object for title generation, or None if skipped.
    :param title_result: The shared result dictionary where the generated title will be stored.
    :param fallback_title: The title to use if generation fails or times out.
    :param mode: The mode of operation ('chat' or 'agent') for metrics labeling.
    :return: The generated title if available, otherwise the fallback title.
    """
    if title_thread is None:
        return (title_result or {}).get("title") or fallback_title

    title_thread.join(timeout=TITLE_GENERATION_JOIN_TIMEOUT_S)
    is_alive_fn = getattr(title_thread, "is_alive", None)
    is_alive = bool(is_alive_fn()) if callable(is_alive_fn) else False
    if is_alive:
        logger.warning(
            "Title generation wait timed out (mode=%s timeout_s=%.2f); using fallback title",
            mode,
            TITLE_GENERATION_JOIN_TIMEOUT_S,
        )
        title_generation_timeout_counter.labels(**metrics_base_labels(), mode=mode).inc()
        return fallback_title

    return (title_result or {}).get("title") or fallback_title


# Config endpoint for frontend
@api_endpoints.route('/config', methods=['GET'])
def get_config():
    """
    Get the configuration for the frontend.

    :return: A JSON response containing the configuration.
    """
    config = {
        "assistantName": ASSISTANT_NAME,
        "assistantNameId": ASSISTANT_NAME_ID,
        "assistantType": ASSISTANT_TYPE.lower(),
        "isAgent": ASSISTANT_TYPE.lower() == "agent",
        "predefinedQuestions": PREDEFINED_QUESTIONS,
        "description": ASSISTANT_DESCRIPTION,
        "showAssistantToggle": SHOW_ASSISTANT_TOGGLE,
        "altToggleLabel": ALT_TOGGLE_LABEL,
        "altAlertMsg": ALT_ALERT_MSG,
        "altAlertType": ALT_ALERT_TYPE,
        "agentFileSizeLimit": AGENT_FILE_SIZE_LIMIT,
        "conversationLoadCutoffDate": CONVERSATION_LOAD_CUTOFF_DATE.isoformat() if CONVERSATION_LOAD_CUTOFF_DATE else None,
    }
    return jsonify(config)


@api_endpoints.route('/threads', methods=['POST'])
def create_thread():
    """
    Create a new thread.

    :return: A JSON response indicating the success or failure of the thread creation.
    """
    try:
        thread_id = azure_client.create_thread()
        return jsonify({"success": True, "message": "Thread created successfully", "thread_id": thread_id})
    except Exception as e:
        logger.error(f"Error creating thread: {e}", exc_info=True)
        return (
            jsonify({
                "success": False,
                "message": "Assistenten havde en midlertidig fejl. Prøv igen senere.",
            }),
            503,
        )


# Endpoint to handle messages in a thread (Agent mode)
@api_endpoints.route('/threads/<thread_id>/messages', methods=['POST'])
def create_thread_message(thread_id):
    """
    Handle messages in a thread (Agent mode).

    :param thread_id: The ID of the thread.
    :return: A JSON response indicating the success or failure of the message handling.
    """
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

    conversation_title = None

    try:
        files = _decode_uploaded_files(files_data, max_size_bytes=AGENT_FILE_SIZE_LIMIT)
    except FileSizeLimitError:
        return jsonify({
            "success": False,
            "message": "En eller flere filer overskrider den tilladte filstørrelse.",
        }), 413

    # Get response from Azure
    try:
        azure_result = azure_client.fetch_chat_response(chat_message=message, files=files, thread_id=thread_id, use_alt=use_alt)
        if isinstance(azure_result, tuple) and len(azure_result) == 4:
            response, refs, error_message, azure_status = azure_result
        else:
            response, refs, error_message = azure_result
            azure_status = None
        logger.debug(
            "Thread message references from azure_client (thread_id=%s count=%s)",
            thread_id,
            len(refs or [])
        )
        if not response:
            return (
                jsonify({"success": False, "message": error_message or "Assistenten havde en midlertidig fejl. Prøv igen senere."}),
                int(azure_status or 500),
            )
    except Exception as e:
        logger.error(f"Error fetching chat response: {e}")
        return (
            jsonify({"success": False, "message": "Assistenten havde en midlertidig fejl. Prøv igen senere."}),
            503,
        )

    if not USE_DB:
        return jsonify({"success": True, "response": response, "references": refs, "conversation_id": conversation_id, "title": conversation_title})

    # Update DB (same semantics as chat mode)
    db_session = None
    try:
        db_session = db_client.get_session()
        if db_session is None:
            logger.error("DB session unavailable for thread message persistence")
            return jsonify({"success": True, "response": response, "references": refs, "conversation_id": conversation_id, "title": conversation_title}), 200

        # Create conversation if missing and we have a user
        if user_email and not conversation_id and message:
            # Start title generation only when DB persistence is possible.
            title_thread, title_result = _start_title_generation_thread(first_user_message=message, mode='agent')
            generated_title = _resolve_title_result(
                title_thread=title_thread,
                title_result=title_result,
                fallback_title=f"Samtale {thread_id}",
                mode='agent',
            )
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
                file_content=_agent_files_for_db(files)
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


@api_endpoints.route('/threads/<thread_id>/messages/stream', methods=['POST'])
def create_thread_message_stream(thread_id):
    """
    Handle messages in a thread (Agent mode) with SSE streaming.

    :param thread_id: The ID of the thread.
    :return: A text/event-stream response with start, delta, end, and error events.
    """
    message = request.json.get("message")
    files_data = request.json.get("files", [])
    use_alt = request.json.get("use_alt", False)
    conversation_id = request.json.get("conversation_id")
    user_email = request.headers.get("X-User-Email") or "guest"

    if not thread_id:
        return jsonify({"success": False, "message": "Der opstod en fejl. Start en ny samtale, genindlæs siden eller prøv igen senere."}), 400
    if not message:
        return jsonify({"success": False, "message": "Der opstod en fejl. Genindlæs siden eller prøv igen senere."}), 400

    if conversation_id in ("", None):
        conversation_id = None
    else:
        try:
            conversation_id = int(conversation_id)
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "Der opstod en fejl. Genindlæs siden eller prøv igen senere."}), 400

    message = redact_content(text=message)

    if count_tokens(message) > MAX_TOKEN_LIMIT_MESSAGE:
        return (
            jsonify({
                "success": False,
                "message": "Din besked er for lang. Reducer længden af din besked og prøv igen."
            }),
            400,
        )

    chat_messages_counter.labels(**metrics_base_labels(), mode='agent').inc()
    try:
        files = _decode_uploaded_files(files_data, max_size_bytes=AGENT_FILE_SIZE_LIMIT)
    except FileSizeLimitError:
        return jsonify({
            "success": False,
            "message": "En eller flere filer overskrider den tilladte filstørrelse.",
        }), 413

    @stream_with_context
    def generate_events():
        local_conversation_id = conversation_id
        conversation_title = None
        refs = []

        yield _sse_event("start", {
            "thread_id": thread_id,
            "conversation_id": local_conversation_id,
        })

        try:
            response_chunks = []
            for stream_event in azure_client.stream_chat_response_with_metadata(
                chat_message=message,
                files=files,
                thread_id=thread_id,
                use_alt=use_alt,
            ):
                event_type = (stream_event or {}).get("type")
                if event_type == "delta":
                    delta = (stream_event or {}).get("text") or ""
                    if delta:
                        response_chunks.append(delta)
                        yield _sse_event("delta", {"text": delta})
                elif event_type == "status":
                    yield _sse_event("status", {
                        "status": (stream_event or {}).get("status") or "working",
                        "message": (stream_event or {}).get("message") or "Assistenten arbejder ...",
                    })
                elif event_type == "references":
                    refs = (stream_event or {}).get("references") or []
                    logger.debug(
                        "Thread stream references event received (thread_id=%s count=%s): %s",
                        thread_id,
                        len(refs),
                        refs,
                    )

            response = "".join(response_chunks).strip()
            if not response:
                yield _sse_event("error", {
                    "message": "Der opstod en fejl ved indlæsning af assistentens svar. Prøv igen senere.",
                    "status": 502,
                })
                return

            if USE_DB:
                db_session = None
                try:
                    db_session = db_client.get_session()
                    if db_session is None:
                        logger.error("DB session unavailable for thread message persistence")
                    else:
                        if user_email and not local_conversation_id and message:
                            title_thread, title_result = _start_title_generation_thread(first_user_message=message, mode='agent')
                            generated_title = _resolve_title_result(
                                title_thread=title_thread,
                                title_result=title_result,
                                fallback_title=f"Samtale {thread_id}",
                                mode='agent',
                            )
                            conversation_title = generated_title

                            created = create_db_conversation(
                                session=db_session,
                                user_email=user_email,
                                title=generated_title,
                                thread_id=thread_id,
                            )
                            if created and getattr(created, "id", None) is not None:
                                chat_conversations_counter.labels(**metrics_base_labels(), mode='agent').inc()
                                local_conversation_id = int(created.id)

                        if local_conversation_id:
                            updated = add_message_to_conversation(
                                session=db_session,
                                conversation_id=local_conversation_id,
                                message_content=message,
                                sender='user',
                                file_content=_agent_files_for_db(files)
                            )
                            if not updated:
                                logger.error("Failed to add user message to conversation in DB")

                            updated = add_message_to_conversation(
                                session=db_session,
                                conversation_id=local_conversation_id,
                                message_content=response,
                                sender='assistant',
                                references=refs
                            )
                            if not updated:
                                logger.error("Failed to add assistant message to conversation in DB")

                except Exception as e:
                    logger.error(f"Error updating conversation in DB: {e}")
                finally:
                    try:
                        if db_session is not None:
                            db_session.close()
                    except Exception:
                        pass

            logger.debug(
                "Thread stream end sent references (thread_id=%s conversation_id=%s count=%s): %s",
                thread_id,
                local_conversation_id,
                len(refs),
                refs,
            )
            yield _sse_event("end", {
                "success": True,
                "response": response,
                "references": refs,
                "conversation_id": local_conversation_id,
                "title": conversation_title,
            })

        except GeneratorExit:
            logger.debug("Client disconnected from SSE stream (thread_id=%s)", thread_id)
            return
        except Exception as e:
            logger.error(f"Error in stream endpoint: {e}", exc_info=True)
            yield _sse_event("error", {
                "message": "Assistenten havde en midlertidig fejl. Prøv igen senere.",
                "status": 503,
            })

    response = Response(generate_events(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


# Endpoint to handle chat messages (Chat mode)
@api_endpoints.route('/chat/messages', methods=['POST'])
def create_chat_message():
    """
    Handle chat messages (Chat mode).

    :return: A JSON response containing the chat response, references, conversation ID, and conversation title.
    """
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
        msg["content"] = redact_content(text=msg.get("content", ""))

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

    conversation_title = None

    # Get response from Azure
    try:
        azure_result = azure_client.fetch_chat_response(chat_messages=messages)
        if isinstance(azure_result, tuple) and len(azure_result) == 4:
            response, refs, error_message, azure_status = azure_result
        else:
            response, refs, error_message = azure_result
            azure_status = None
        logger.debug(
            "Chat message references from azure_client (conversation_id=%s count=%s)",
            conversation_id,
            len(refs or [])
        )
        if not response:
            return (
                jsonify({"success": False, "message": error_message or "Assistenten havde en midlertidig fejl. Prøv igen senere."}),
                int(azure_status or 500),
            )
    except Exception as e:
        logger.error(f"Error fetching chat response: {e}")
        return (
            jsonify({"success": False, "message": "Assistenten havde en midlertidig fejl. Prøv igen senere."}),
            503,
        )

    if not USE_DB:
        return jsonify({"success": True, "response": response, "references": refs, "conversation_id": conversation_id, "title": conversation_title})

    # Update DB
    db_session = None
    try:
        db_session = db_client.get_session()
        if db_session is None:
            logger.error("DB session unavailable for chat message persistence")
            return jsonify({"success": True, "response": response, "references": refs, "conversation_id": conversation_id, "title": conversation_title})

        # Create conversation in DB if conversation id is not provided
        if user_email and not conversation_id:
            first_user_message = next(
                (m.get("content", "") for m in messages if m.get("role") == "user"),
                ""
            )
            title_thread = None
            title_result = None
            if first_user_message:
                # Start title generation only when DB persistence is possible.
                title_thread, title_result = _start_title_generation_thread(first_user_message=first_user_message, mode='chat')
            generated_title = _resolve_title_result(
                title_thread=title_thread,
                title_result=title_result,
                fallback_title="Ny samtale",
                mode='chat',
            )
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

        if not USE_DB:
            return jsonify({"success": False, "message": "Kunne ikke indlæse samtalen. Prøv igen senere."}), 503

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
    """
    Filter content using the configured content filter.

    :return: A JSON response containing the filtered content.
    """
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
    """
    Send user feedback for a specific chat response.

    :return: A JSON response indicating the success or failure of the feedback submission.
    """
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
    """
    Send a "like" feedback for a specific chat response (metrics counter).

    :return: A JSON response indicating the success of the feedback submission.
    """
    chat_feedback_counter.labels(**metrics_base_labels(), feedback_type='like').inc()
    return jsonify({"success": True})
