import logging
import os
import random
import time
from abc import abstractmethod
from json import JSONDecodeError

from azure.ai.projects import AIProjectClient
from azure.core.exceptions import ServiceRequestError
from azure.identity import DefaultAzureCredential
from openai import AzureOpenAI

from utils.config import (
    AGENT_ALT_ID,
    AGENT_ID,
    ASSISTANT_ALT_ID,
    ASSISTANT_NAME,
    ASSISTANT_TYPE,
    AZURE_AIFOUNDRY_PROJECT_NAME,
    AZURE_API_VERSION_OPENAI,
    AZURE_OPENAI_DEPLOYMENT_NAME_TITLE_GENERATION,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    MAX_MESSAGE_LENGTH,
    TITLE_GENERATION_REQUEST_TIMEOUT_S,
)


logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _safe_status_code(exc: Exception) -> int | None:
    """
    Safely extract the status code from an exception.

    :param exc: The exception to inspect.
    :return: HTTP status code if available.
    """
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(exc, "response", None)
    for attr in ("status_code", "status", "http_status"):
        value = getattr(response, attr, None) if response is not None else None
        if isinstance(value, int):
            return value
    return None


def _is_retryable_exception(exc: Exception) -> bool:
    """
    Determine whether a failure is likely transient.

    :param exc: The exception to inspect.
    :return: True for retryable errors.
    """
    if isinstance(exc, (ServiceRequestError, TimeoutError, JSONDecodeError)):
        return True

    status_code = _safe_status_code(exc=exc)
    if status_code in _RETRYABLE_STATUS_CODES:
        return True

    msg = str(exc or "").lower()
    if "timeout" in msg or "timed out" in msg or "temporarily" in msg:
        return True
    if "internal server error" in msg:
        return True
    return False


def _error_to_user_message_and_status(exc: Exception) -> tuple[str, int]:
    """
    Map internal errors to user-facing messages.

    :param exc: The exception to convert.
    :return: (message, http_status)
    """
    status_code = _safe_status_code(exc=exc)

    if status_code == 429:
        return "Assistenten er travl lige nu. Prov igen om lidt.", 429
    if status_code in (401, 403):
        return "Assistenten er ikke korrekt konfigureret. Prov igen senere.", 503
    if status_code == 404:
        return "Der opstod en fejl med samtalen. Start en ny samtale og prov igen.", 400
    if status_code is not None and 400 <= status_code < 500:
        return "Der opstod en fejl i foresporgslen. Genindlaes siden eller prov igen senere.", 400

    if _is_retryable_exception(exc=exc):
        return "Assistenten havde en midlertidig fejl. Prov igen om lidt.", 503

    return "Assistenten havde en midlertidig fejl. Prov igen om lidt.", 500


def _call_with_retries(*, operation: str, func, max_retries: int = 1, base_delay_s: float = 0.4):
    """
    Execute an operation with a small retry budget for transient failures.

    :param operation: Operation name for logs.
    :param func: Callable to execute.
    :param max_retries: Number of retries after first attempt.
    :param base_delay_s: Base delay used for exponential backoff.
    :return: Result from func().
    """
    attempt = 0
    while True:
        try:
            return func()
        except Exception as exc:
            if _is_retryable_exception(exc=exc) and attempt < max_retries:
                delay = base_delay_s * (2 ** attempt) + random.uniform(0.0, 0.2)
                logger.warning(
                    "Azure op failed (op=%s attempt=%s/%s): %s; retrying in %.2fs",
                    operation,
                    attempt + 1,
                    max_retries + 1,
                    exc,
                    delay,
                )
                time.sleep(delay)
                attempt += 1
                continue

            logger.error("Azure op failed (op=%s attempts=%s): %s", operation, attempt + 1, exc, exc_info=True)
            raise


def _build_project_endpoint() -> str:
    """
    Resolve the AI Foundry project endpoint.

    :return: Full endpoint URL.
    :raises ValueError: if no usable endpoint configuration exists.
    """
    endpoint = os.environ.get("AZURE_AIFOUNDRY_PROJECT_ENDPOINT", "").strip()
    if not endpoint:
        endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()

    if endpoint:
        return endpoint

    if not AZURE_AIFOUNDRY_PROJECT_NAME:
        raise ValueError(
            "Missing AI Foundry endpoint configuration. Set AZURE_AIFOUNDRY_PROJECT_ENDPOINT "
            "or FOUNDRY_PROJECT_ENDPOINT."
        )

    return f"https://sc-oai-it.services.ai.azure.com/api/projects/{AZURE_AIFOUNDRY_PROJECT_NAME}"


class AzureOpenAIClient:
    """
    Base interface used by the API endpoints.
    """

    def __init__(self):
        self.assistant_name = ASSISTANT_NAME
        self.assistant_type = ASSISTANT_TYPE

    def close(self) -> None:
        """
        Close any resources held by the client.
        """
        try:
            close_fn = getattr(self, "client", None)
            close_callable = getattr(close_fn, "close", None)
            if callable(close_callable):
                close_callable()
        except Exception:
            pass

    def get_client(self):
        """
        Get raw SDK client.

        :return: SDK client instance.
        """
        return getattr(self, "client", None)

    @abstractmethod
    def fetch_chat_response(self, **args) -> tuple[str | None, list[dict], str | None, int]:
        """
        Fetch a chat response.

        :param args: Client-specific arguments.
        :return: (assistant_response, citations, error_message, http_status)
        """
        pass


class Agent(AzureOpenAIClient):
    """
    Agent-only client using AI Foundry conversations plus responses API.
    """

    def __init__(self):
        super().__init__()
        self._closed = False

        self._credential = DefaultAzureCredential()
        self._project = AIProjectClient(
            endpoint=_build_project_endpoint(),
            credential=self._credential,
        )

        if AZURE_OPENAI_KEY:
            self.client = self._project.get_openai_client(api_key=AZURE_OPENAI_KEY)
        else:
            self.client = self._project.get_openai_client()

        self.agent_id = (AGENT_ID or "").strip()
        self.agent_alt_id = (AGENT_ALT_ID or "").strip() or None
        self.agent_version = os.environ.get("FOUNDRY_AGENT_VERSION", "").strip() or None
        self.alt_agent_version = os.environ.get("FOUNDRY_AGENT_ALT_VERSION", "").strip() or None

        # Backwards-compatible fallback if alternate agent id is only supplied via ASSISTANT_ALT_ID.
        if not self.agent_alt_id and ASSISTANT_ALT_ID:
            self.agent_alt_id = ASSISTANT_ALT_ID

    def close(self) -> None:
        """
        Close open resources in reverse dependency order.
        """
        if self._closed:
            return
        self._closed = True

        try:
            close_fn = getattr(self.client, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass

        try:
            close_fn = getattr(self._project, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass

        try:
            close_fn = getattr(self._credential, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass

    def _resolve_agent_reference(self, use_alt: bool) -> dict:
        """
        Build agent_reference payload for responses API.

        :param use_alt: Whether alternate agent should be used.
        :return: agent_reference dict.
        :raises ValueError: if no agent id is configured.
        """
        selected_agent_id = self.agent_alt_id if use_alt and self.agent_alt_id else self.agent_id
        selected_agent_version = self.alt_agent_version if use_alt and self.agent_alt_id else self.agent_version

        if not selected_agent_id:
            raise ValueError("Missing agent id. Set AGENT_ID.")

        ref = {
            "name": selected_agent_id,
            "type": "agent_reference",
        }
        if selected_agent_version:
            ref["version"] = selected_agent_version
        return ref

    def _prepare_response_input(self, *, chat_message: str | None, files) -> list[dict]:
        """
        Build Responses API message content with uploaded file ids.

        :param chat_message: User text.
        :param files: Uploaded file objects from the API layer.
        :return: Responses input payload.
        """
        content = [{"type": "input_text", "text": chat_message or ""}]

        if files:
            for index, file in enumerate(files):
                filename = getattr(file, "filename", None)
                if not filename:
                    filename = getattr(file, "name", None)
                if not filename:
                    filename = f"upload_{index + 1}.bin"
                seek_fn = getattr(file, "seek", None)
                if callable(seek_fn):
                    seek_fn(0)

                uploaded = _call_with_retries(
                    operation="openai.files.create",
                    func=lambda f=file, n=filename: self.client.files.create(
                        purpose="assistants",
                        file=(n, f),
                    ),
                )
                file_id = getattr(uploaded, "id", None)
                if not file_id:
                    raise ValueError("File upload completed without file id")

                content.append({"type": "input_file", "file_id": file_id})

        return [{"role": "user", "content": content}]

    def fetch_chat_response(self, chat_message, files, thread_id, use_alt=False) -> tuple[str | None, list[dict], str | None, int]:
        """
        Send one user turn to an existing conversation and collect the streamed text response.

        :param chat_message: Latest user message.
        :param files: Optional uploaded files.
        :param thread_id: Conversation id from create_thread().
        :param use_alt: Use alternate configured agent reference if available.
        :return: (assistant_response, citations, error_message, http_status)
        """
        if not thread_id:
            return (
                None,
                [],
                "Der opstod en fejl med samtalen. Prov at genindlaese siden, eller start en ny samtale.",
                400,
            )

        message_text = chat_message or ""
        if len(message_text) > MAX_MESSAGE_LENGTH:
            has_files = bool(files)
            return (
                None,
                [],
                (
                    f"Din besked er for lang{', eller dine dokumenter er for store.' if has_files else '.'} "
                    f"Reducer laengden af din besked{', eller fjern nogle dokumenter' if has_files else ''} og prov igen."
                ),
                400,
            )

        try:
            agent_reference = self._resolve_agent_reference(use_alt=use_alt)
            response_input = self._prepare_response_input(chat_message=chat_message, files=files)

            stream = _call_with_retries(
                operation="openai.responses.create",
                func=lambda: self.client.responses.create(
                    conversation=thread_id,
                    input=response_input,
                    stream=True,
                    extra_body={"agent_reference": agent_reference},
                ),
            )

            response_chunks = []
            for event in stream:
                if getattr(event, "type", None) == "response.output_text.delta" and getattr(event, "delta", None):
                    response_chunks.append(event.delta)

            assistant_response = "".join(response_chunks).strip()
            if not assistant_response:
                return None, [], "Der opstod en fejl ved indlaesning af assistentens svar. Prov igen om lidt.", 502

            # Prototype: citations are not extracted yet from the streaming events.
            return assistant_response, [], None, 200

        except Exception as exc:
            msg, status = _error_to_user_message_and_status(exc=exc)
            return None, [], msg, status

    def create_thread(self) -> str:
        """
        Create one conversation id that is reused across turns.

        :return: Conversation id.
        """
        conversation = _call_with_retries(
            operation="openai.conversations.create",
            func=lambda: self.client.conversations.create(),
        )

        conversation_id = getattr(conversation, "id", None)
        if not conversation_id:
            raise ValueError("Failed to create conversation id")
        return conversation_id


class AzureOpenAITitleGenerator:
    def __init__(self):
        self.client = AzureOpenAI(
            api_version=AZURE_API_VERSION_OPENAI,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
        )
        self.deployment_name = AZURE_OPENAI_DEPLOYMENT_NAME_TITLE_GENERATION

    def generate_title(self, conversation_messages):
        """
        Generate a short title from the first user message.

        :param conversation_messages: Conversation message list.
        :return: Suggested title.
        """
        system_prompt = {
            "role": "system",
            "content": (
                "Du er en hjaelpsom assistent, der genererer korte og praecise titler "
                "(maksimalt 24 tegn) til samtaler baseret pa brugerens forste besked. "
                "Titlen skal vaere pa dansk og opsummere samtalens emne uden at inkludere "
                "citater eller referencer."
            ),
        }
        user_prompt = {
            "role": "user",
            "content": f"Generer en kort titel for folgende besked: '{conversation_messages[0]['content']}'",
        }

        response = self.client.chat.completions.create(
            messages=[system_prompt, user_prompt],
            temperature=0.5,
            top_p=0.9,
            model=self.deployment_name,
            timeout=TITLE_GENERATION_REQUEST_TIMEOUT_S,
        )

        if response and hasattr(response, "choices") and len(response.choices) > 0:
            choice = response.choices[0]
            if hasattr(choice, "message") and hasattr(choice.message, "content"):
                return choice.message.content.strip().strip('"').strip("'")

        return "Ny samtale"


def get_chat_client() -> AzureOpenAIClient:
    """
    Return the new prototype agent client.

    :return: Agent client.
    """
    if str(ASSISTANT_TYPE).lower() != "agent":
        logger.warning("azure_openai2 prototype only supports Agent mode. ASSISTANT_TYPE=%s", ASSISTANT_TYPE)
    return Agent()


def get_title_generator() -> AzureOpenAITitleGenerator:
    """
    Return title generator instance.

    :return: AzureOpenAITitleGenerator
    """
    return AzureOpenAITitleGenerator()

# End of module.
