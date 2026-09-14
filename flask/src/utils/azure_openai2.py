import datetime
import html
import logging
import os
import random
import re
import time
import urllib.parse
from abc import abstractmethod
from json import JSONDecodeError, loads
from typing import Any

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
    AZURE_AISEARCH_ENDPOINT,
    AZURE_AISEARCH_INDEX_NAME,
    AZURE_AISEARCH_SEMANTIC_CONFIG,
    AZURE_AIFOUNDRY_PROJECT_NAME,
    AZURE_API_VERSION_OPENAI,
    AZURE_OPENAI_DEPLOYMENT_NAME,
    AZURE_OPENAI_DEPLOYMENT_NAME_TITLE_GENERATION,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    DEFAULT_TOKEN_ENCODING,
    EMPHASIZE_RECENT_CONTENT,
    MAX_MESSAGE_LENGTH,
    MAX_TOKEN_LIMIT_HISTORY,
    MAX_TOKEN_LIMIT_MESSAGE,
    SEARCH_STRICTNESS,
    SYSTEM_PROMPT,
    TEMPERATURE_VALUE,
    TITLE_GENERATION_REQUEST_TIMEOUT_S,
    TOP_N_DOCUMENTS,
    TOP_P_VALUE,
    USE_GENERAL_KNOWLEDGE,
)
from utils.extract_filedata import extract_text_from_file


logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _get_token_encoding(deployment_name: str):
    """Resolve the tokenizer used only by the legacy Chat client."""
    import tiktoken

    try:
        return tiktoken.encoding_for_model(deployment_name)
    except KeyError:
        return tiktoken.get_encoding(DEFAULT_TOKEN_ENCODING)


def _get_field(obj: Any, name: str, default: Any = None) -> Any:
    """
    Read a field from either dict-like or object-like values.

    :param obj: Source object.
    :param name: Field name.
    :param default: Fallback value.
    :return: Field value or default.
    """
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _extract_output_text_annotations_from_message_item(item: Any) -> list[Any]:
    """
    Extract output_text annotations from one response output item.

    :param item: Response output item.
    :return: Flat list of annotations.
    """
    annotations: list[Any] = []
    if _get_field(item, "type") != "message":
        return annotations

    for content_item in _get_field(item, "content", []) or []:
        if _get_field(content_item, "type") != "output_text":
            continue
        for annotation in _get_field(content_item, "annotations", []) or []:
            normalized = _to_jsonable(annotation)
            if isinstance(normalized, dict):
                annotations.append(normalized)

    return annotations


def _extract_web_search_urls_from_item(item: Any) -> list[str]:
    """
    Extract source URLs from one web_search_call output item.

    :param item: Response output item.
    :return: Ordered URL list.
    """
    if _get_field(item, "type") != "web_search_call":
        return []

    action = _get_field(item, "action")
    action_type = str(_get_field(action, "type") or "").strip()

    urls: list[str] = []
    if action_type == "search":
        for source in _get_field(action, "sources", []) or []:
            url = str(_get_field(source, "url") or "").strip()
            if url:
                urls.append(url)
    elif action_type in {"open_page", "find"}:
        url = str(_get_field(action, "url") or "").strip()
        if url:
            urls.append(url)

    return urls


def _extract_web_search_url_citations(output_items: list[Any]) -> list[dict]:
    """
    Create url_citation objects from web_search_call source URLs.

    :param output_items: Response output list.
    :return: List of native-looking url_citation objects.
    """
    seen: set[str] = set()
    references: list[dict] = []

    for item in output_items or []:
        for url in _extract_web_search_urls_from_item(item=item):
            if url in seen:
                continue
            seen.add(url)
            references.append({
                "type": "url_citation",
                "title": url,
                "url": url,
            })

    return references


def _extract_bing_grounding_url_citations(output_items: list[Any]) -> list[dict]:
    """Extract public source links from loosely typed Bing grounding outputs."""
    seen: set[str] = set()
    references: list[dict] = []

    def visit(value: Any) -> None:
        normalized = _to_jsonable(value)
        if isinstance(normalized, str):
            try:
                normalized = loads(normalized)
            except (JSONDecodeError, TypeError):
                return

        if isinstance(normalized, list):
            for entry in normalized:
                visit(entry)
            return

        if not isinstance(normalized, dict):
            return

        url = str(normalized.get("url") or normalized.get("link") or "").strip()
        if url.startswith(("https://", "http://")) and url not in seen:
            seen.add(url)
            title = str(normalized.get("title") or normalized.get("name") or url).strip()
            references.append({
                "type": "url_citation",
                "title": title or url,
                "url": url,
            })

        for nested in normalized.values():
            if isinstance(nested, (dict, list)):
                visit(nested)

    for item in output_items or []:
        if _get_field(item, "type") == "bing_grounding_call_output":
            visit(_get_field(item, "output"))

    return references


def _summarize_output_item_for_logs(item: Any) -> dict:
    """
    Build a compact structural summary for one response output item.

    :param item: Response output item.
    :return: Summary dict without message content.
    """
    item_type = str(_get_field(item, "type") or "")
    summary: dict[str, Any] = {"type": item_type}

    if item_type == "message":
        content_items = list(_get_field(item, "content", []) or [])
        output_text_parts = [part for part in content_items if _get_field(part, "type") == "output_text"]
        summary["content_parts"] = len(content_items)
        summary["output_text_parts"] = len(output_text_parts)
        summary["annotation_count"] = sum(len(_get_field(part, "annotations", []) or []) for part in output_text_parts)
        return summary

    if item_type == "web_search_call":
        action = _get_field(item, "action")
        action_type = str(_get_field(action, "type") or "")
        summary["action_type"] = action_type
        if action_type == "search":
            summary["source_count"] = len(_get_field(action, "sources", []) or [])
        else:
            summary["has_url"] = bool(str(_get_field(action, "url") or "").strip())
        return summary

    return summary


def _status_for_stream_event(event: Any) -> dict[str, str] | None:
    """Map Foundry stream structure to a privacy-safe user-facing status."""
    event_type = _get_field(event, "type")

    if event_type in {"response.output_item.added", "response.output_item.done"}:
        item_type = _get_field(_get_field(event, "item"), "type")
        statuses = {
            "reasoning": ("thinking", "Assistenten tænker ..."),
            "web_search_call": ("web_search", "Assistenten søger på nettet ..."),
            "bing_grounding_call": ("web_search", "Assistenten søger på nettet ..."),
            "file_search_call": ("file_search", "Assistenten søger i filer ..."),
            "code_interpreter_call": ("working", "Assistenten bearbejder data ..."),
            "message": ("answering", "Assistenten svarer ..."),
        }
        status = statuses.get(item_type)
        if status:
            return {"status": status[0], "message": status[1]}

    if event_type in {"response.content_part.added", "response.content_part.done"}:
        if _get_field(_get_field(event, "part"), "type") in {"output_text", "text"}:
            return {"status": "answering", "message": "Assistenten svarer ..."}

    if event_type == "response.output_text.delta":
        return {"status": "answering", "message": "Assistenten svarer ..."}

    return None


def _to_jsonable(value: Any) -> Any:
    """
    Convert SDK model objects to plain JSON-serializable Python values.

    :param value: Value from SDK stream event.
    :return: JSON-compatible Python value.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _to_jsonable(model_dump())
        except Exception:
            pass

    dict_fn = getattr(value, "dict", None)
    if callable(dict_fn):
        try:
            return _to_jsonable(dict_fn())
        except Exception:
            pass

    return value


def _extract_native_annotations_from_stream_event(event: Any) -> list[dict] | None:
    """
    Extract native citation annotations from a streamed Responses event.

    :param event: Stream event.
    :return: Annotation list or None when event does not carry annotations.
    """
    event_type = _get_field(event, "type")

    if event_type == "response.output_text.annotation.added":
        annotation = _get_field(event, "annotation")
        normalized = _to_jsonable(annotation)
        if isinstance(normalized, dict):
            return [normalized]
        return None

    if event_type == "response.content_part.done":
        part = _get_field(event, "part")
        if _get_field(part, "type") == "output_text":
            annotations = [_to_jsonable(a) for a in (_get_field(part, "annotations", []) or [])]
            annotations = [a for a in annotations if isinstance(a, dict)]
            if not annotations:
                return None
            return annotations

    if event_type == "response.content_part.added":
        part = _get_field(event, "part")
        if _get_field(part, "type") == "output_text":
            annotations = [_to_jsonable(a) for a in (_get_field(part, "annotations", []) or [])]
            annotations = [a for a in annotations if isinstance(a, dict)]
            if not annotations:
                return None
            return annotations

    if event_type == "response.output_item.added":
        item = _get_field(event, "item")

        grounding_refs = _extract_web_search_url_citations(output_items=[item])
        if not grounding_refs:
            grounding_refs = _extract_bing_grounding_url_citations(output_items=[item])
        if grounding_refs:
            return grounding_refs

        annotations = _extract_output_text_annotations_from_message_item(item=item)
        if not annotations:
            return None
        return annotations

    if event_type == "response.output_item.done":
        item = _get_field(event, "item")

        grounding_refs = _extract_web_search_url_citations(output_items=[item])
        if not grounding_refs:
            grounding_refs = _extract_bing_grounding_url_citations(output_items=[item])
        if grounding_refs:
            return grounding_refs

        annotations = _extract_output_text_annotations_from_message_item(item=item)
        if not annotations:
            return None
        return annotations

    if event_type == "response.completed":
        response = _get_field(event, "response")
        output_items = list(_get_field(response, "output", []) or [])

        grounding_refs = _extract_web_search_url_citations(output_items=output_items)
        if not grounding_refs:
            grounding_refs = _extract_bing_grounding_url_citations(output_items=output_items)

        annotations: list[Any] = []
        for output_item in output_items:
            annotations.extend(_extract_output_text_annotations_from_message_item(item=output_item))
        if annotations:
            return annotations
        if grounding_refs:
            return grounding_refs
        return None

    return None


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


class Chat(AzureOpenAIClient):
    """
    Legacy ChatCompletions client with optional Azure AI Search grounding.
    """

    def __init__(self):
        super().__init__()
        self.client = AzureOpenAI(
            api_version=AZURE_API_VERSION_OPENAI,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
        )
        self.search_endpoint = AZURE_AISEARCH_ENDPOINT
        self.search_index = AZURE_AISEARCH_INDEX_NAME
        self.semantic_config = AZURE_AISEARCH_SEMANTIC_CONFIG
        self.deployment_name = AZURE_OPENAI_DEPLOYMENT_NAME
        self.use_general_knowledge = USE_GENERAL_KNOWLEDGE
        self.emphasize_recent_content = EMPHASIZE_RECENT_CONTENT
        self.top_p = TOP_P_VALUE
        self.temperature = TEMPERATURE_VALUE
        self.top_n_documents = TOP_N_DOCUMENTS
        self.search_strictness = SEARCH_STRICTNESS

    def get_system_prompt(self) -> str:
        """Return the configured legacy system prompt."""
        system_prompt = SYSTEM_PROMPT.strip()
        if self.emphasize_recent_content:
            weekdays_danish = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lordag", "Sondag"]
            now = datetime.datetime.now()
            date = f"{weekdays_danish[now.weekday()]} d. {now.strftime('%d-%m-%Y')}"
            system_prompt += f"\nDagens dato er {date}, og du skal altid bruge den nyeste information, der er tilgaengelig."
        return system_prompt

    @staticmethod
    def parse_urlencoding(value):
        """Decode a URL-encoded string."""
        if not value:
            return value
        return urllib.parse.unquote(value)

    @staticmethod
    def sort_refs(match):
        refs = re.findall(r"\[(\d+)\]", match.group(0))
        return "".join(f"[{ref}]" for ref in sorted(int(ref) for ref in refs))

    def fetch_chat_response(self, chat_messages) -> tuple[str | None, list[dict], str | None, int]:
        """
        Fetch a response through the legacy Azure OpenAI ChatCompletions API.

        :param chat_messages: Conversation history, optionally including uploaded files.
        :return: (assistant_response, citations, error_message, http_status)
        """
        ai_search_body = {}
        if self.search_endpoint and self.search_index:
            ai_search_body = {
                "data_sources": [
                    {
                        "type": "azure_search",
                        "parameters": {
                            "endpoint": self.search_endpoint,
                            "index_name": self.search_index,
                            "semantic_configuration": self.semantic_config,
                            "query_type": "semantic",
                            "fields_mapping": {},
                            "in_scope": not self.use_general_knowledge,
                            "filter": None,
                            "strictness": self.search_strictness,
                            "top_n_documents": self.top_n_documents,
                            "authentication": {"type": "system_assigned_managed_identity"},
                        },
                    }
                ]
            }

        request_messages = [{"role": "system", "content": self.get_system_prompt()}]
        for chat_message in chat_messages:
            request_message = {
                "role": chat_message["role"],
                "content": chat_message["content"],
            }
            files = chat_message.get("files") or []
            if files and chat_message["role"] == "user":
                file_count = len(files)
                document_word = "dokumenter" if file_count > 1 else "dokument"
                document_reference = "de uploadede dokumenter" if file_count > 1 else "det uploadede dokument"
                request_message["content"] += (
                    f"\n\n# Der er uploadet {file_count} {document_word}. Benyt folgende indhold fra "
                    f"{document_reference} som kontekst for foresporgslen:\n\n"
                )
                for index, file in enumerate(files):
                    document_text = extract_text_from_file(file=file)
                    request_message["content"] += (
                        f"\n\n## Dokument {index + 1}: {file.filename}\n### Indhold:\n\n{document_text}"
                    )
            request_messages.append(request_message)

        encoding = _get_token_encoding(self.deployment_name)

        latest_message_tokens = len(encoding.encode(request_messages[-1]["content"]))
        if latest_message_tokens > MAX_TOKEN_LIMIT_MESSAGE:
            has_files = bool(chat_messages[-1].get("files"))
            return (
                None,
                [],
                f"Din besked er for lang{', eller dine dokumenter er for store.' if has_files else '.'} "
                f"Reducer laengden af din besked{', eller fjern nogle dokumenter' if has_files else ''} og prov igen.",
                400,
            )

        total_tokens = sum(
            len(encoding.encode(message.get("content", "")))
            for message in request_messages
            if isinstance(message.get("content"), str)
        )
        if total_tokens > MAX_TOKEN_LIMIT_HISTORY:
            has_files = any(message.get("files") for message in chat_messages if message.get("role") == "user")
            return (
                None,
                [],
                f"Din samtale er for lang{', eller dine dokumenter er for store.' if has_files else '.'} "
                "Overvej at starte en ny samtale.",
                400,
            )

        try:
            response = _call_with_retries(
                operation="openai.chat.completions.create",
                func=lambda: self.client.chat.completions.create(
                    messages=request_messages,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    model=self.deployment_name,
                    extra_body=ai_search_body,
                ),
            )
        except Exception as exc:
            message, status = _error_to_user_message_and_status(exc=exc)
            return None, [], message, status

        if not response or not getattr(response, "choices", None):
            return None, [], "Der opstod en fejl ved indlaesning af assistentens svar. Prov igen om lidt.", 502

        choice = response.choices[0]
        response_message = getattr(choice, "message", None)
        assistant_response = getattr(response_message, "content", None)
        if assistant_response is None:
            return None, [], "Der opstod en fejl ved indlaesning af assistentens svar. Prov igen om lidt.", 502

        citation_refs = [int(ref) for ref in re.findall(r"\[(?:doc)?(\d{1,2})\]", assistant_response)]
        unique_refs = sorted(set(citation_refs))
        context = getattr(response_message, "context", None) or {}
        all_citations = context.get("citations", []) if hasattr(context, "get") else []

        ordered_urls = []
        for ref in unique_refs:
            if 0 < ref <= len(all_citations):
                citation = all_citations[ref - 1]
                url = citation.get("url") if hasattr(citation, "get") else None
                if url not in ordered_urls:
                    ordered_urls.append(url)

        url_index_map = []
        for url in ordered_urls:
            matching_citation = next(
                (citation for citation in all_citations if citation and citation.get("url") == url),
                {},
            )
            url_index_map.append({
                "type": "url_citation",
                "url": self.parse_urlencoding(url),
                "title": self.parse_urlencoding(matching_citation.get("title")),
                "refs": [
                    index + 1
                    for index, citation in enumerate(all_citations)
                    if citation and citation.get("url") == url
                ],
            })

        referenced_citations = [
            item for item in url_index_map if any(ref in item["refs"] for ref in unique_refs)
        ]

        def replace_ref(match):
            original_ref = int(match.group(1))
            if 0 < original_ref <= len(all_citations):
                citation_url = self.parse_urlencoding(all_citations[original_ref - 1].get("url"))
                for index, url_info in enumerate(url_index_map):
                    if url_info["url"] == citation_url:
                        return f"[{index + 1}]"
            return f"[{original_ref}]"

        assistant_response = re.sub(r"\[(?:doc)?(\d{1,2})\]", replace_ref, assistant_response)
        assistant_response = re.sub(r"(\[\d+\])(?:\1)+", r"\1", assistant_response)
        assistant_response = re.sub(r"(\[\d+\]){2,}", self.sort_refs, assistant_response)

        def replace_numbered_ref(match):
            reference_index = int(match.group(1)) - 1
            if 0 <= reference_index < len(url_index_map):
                reference = url_index_map[reference_index]
                label = reference.get("title") or reference.get("url") or "Reference"
                return f'<span class="inline-reference">[{html.escape(str(label))}]</span>'
            return match.group(0)

        assistant_response = re.sub(r"\[(\d+)\]", replace_numbered_ref, assistant_response)

        return assistant_response, referenced_citations, None, 200


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
            response_chunks = []
            references = []
            for stream_event in self.stream_chat_response_with_metadata(
                chat_message=chat_message,
                files=files,
                thread_id=thread_id,
                use_alt=use_alt,
            ):
                if stream_event.get("type") == "delta":
                    response_chunks.append(stream_event.get("text", ""))
                elif stream_event.get("type") == "references":
                    references = stream_event.get("references") or []
                    logger.info(
                        "Agent fetch received references event (thread_id=%s count=%s): %s",
                        thread_id,
                        len(references),
                        references,
                    )

            assistant_response = "".join(response_chunks).strip()
            if not assistant_response:
                return None, [], "Der opstod en fejl ved indlaesning af assistentens svar. Prov igen om lidt.", 502

            logger.info(
                "Agent fetch completed with references (thread_id=%s count=%s): %s",
                thread_id,
                len(references),
                references,
            )

            return assistant_response, references, None, 200

        except Exception as exc:
            msg, status = _error_to_user_message_and_status(exc=exc)
            return None, [], msg, status

    def stream_chat_response(self, chat_message, files, thread_id, use_alt=False):
        """
        Stream assistant text deltas for one user turn.

        :param chat_message: Latest user message.
        :param files: Optional uploaded files.
        :param thread_id: Conversation id from create_thread().
        :param use_alt: Use alternate configured agent reference if available.
        :yield: Text delta chunks from the assistant response.
        """
        for stream_event in self.stream_chat_response_with_metadata(
            chat_message=chat_message,
            files=files,
            thread_id=thread_id,
            use_alt=use_alt,
        ):
            if stream_event.get("type") == "delta" and stream_event.get("text"):
                yield stream_event["text"]

    def stream_chat_response_with_metadata(self, chat_message, files, thread_id, use_alt=False):
        """
        Stream assistant text deltas and emit final native citation annotations.

        :param chat_message: Latest user message.
        :param files: Optional uploaded files.
        :param thread_id: Conversation id from create_thread().
        :param use_alt: Use alternate configured agent reference if available.
        :yield: Dict events containing status, text delta, or reference metadata.
        """
        if not thread_id:
            raise ValueError("Missing thread id")

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

        latest_references: list[dict] = []
        streamed_annotations: list[Any] = []
        references_emitted = False
        last_status = None

        for event in stream:
            event_type = getattr(event, "type", None)

            status = _status_for_stream_event(event=event)
            if status and status["status"] != last_status:
                last_status = status["status"]
                yield {"type": "status", **status}

            if event_type in {"response.output_item.added", "response.output_item.done"}:
                item = _get_field(event, "item")
                logger.info(
                    "Agent stream output item event (thread_id=%s event=%s summary=%s)",
                    thread_id,
                    event_type,
                    _summarize_output_item_for_logs(item),
                )

            if event_type in {"response.content_part.added", "response.content_part.done"}:
                part = _get_field(event, "part")
                if _get_field(part, "type") == "output_text":
                    logger.info(
                        "Agent stream content part event (thread_id=%s event=%s annotation_count=%s)",
                        thread_id,
                        event_type,
                        len(_get_field(part, "annotations", []) or []),
                    )

            if event_type == "response.completed":
                response = _get_field(event, "response")
                output_items = list(_get_field(response, "output", []) or [])
                logger.info(
                    "Agent stream completed event summary (thread_id=%s output_items=%s summaries=%s)",
                    thread_id,
                    len(output_items),
                    [_summarize_output_item_for_logs(item) for item in output_items],
                )

            if event_type == "response.output_text.delta" and getattr(event, "delta", None):
                yield {"type": "delta", "text": event.delta}

            # Web/file citations can be streamed incrementally via annotation.added events.
            if event_type == "response.output_text.annotation.added":
                annotation = _get_field(event, "annotation")
                normalized = _to_jsonable(annotation)
                if isinstance(normalized, dict):
                    streamed_annotations.append(normalized)
                    latest_references = list(streamed_annotations)
                    logger.info(
                        "Agent stream annotation added (thread_id=%s total=%s): %s",
                        thread_id,
                        len(latest_references),
                        normalized,
                    )
                continue

            extracted_references = _extract_native_annotations_from_stream_event(event=event)
            if extracted_references:
                latest_references = extracted_references
                logger.info(
                    "Agent stream references extracted (thread_id=%s event=%s count=%s): %s",
                    thread_id,
                    event_type,
                    len(latest_references),
                    latest_references,
                )
                if event_type == "response.completed":
                    logger.info(
                        "Agent stream emitting references at completed (thread_id=%s count=%s): %s",
                        thread_id,
                        len(latest_references),
                        latest_references,
                    )
                    yield {"type": "references", "references": latest_references}
                    references_emitted = True

            if event_type == "response.completed" and not references_emitted:
                if not latest_references and streamed_annotations:
                    latest_references = list(streamed_annotations)
                logger.info(
                    "Agent stream emitting fallback references at completed (thread_id=%s count=%s): %s",
                    thread_id,
                    len(latest_references),
                    latest_references,
                )
                yield {"type": "references", "references": latest_references}
                references_emitted = True

        if not references_emitted:
            logger.info(
                "Agent stream emitting end-of-stream references (thread_id=%s count=%s): %s",
                thread_id,
                len(latest_references),
                latest_references,
            )
            yield {"type": "references", "references": latest_references}

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
    Return the configured Agent client or the legacy Chat client.

    :return: Configured chat client.
    """
    if str(ASSISTANT_TYPE).lower() == "agent":
        return Agent()
    return Chat()


def get_title_generator() -> AzureOpenAITitleGenerator:
    """
    Return title generator instance.

    :return: AzureOpenAITitleGenerator
    """
    return AzureOpenAITitleGenerator()

# End of module.
