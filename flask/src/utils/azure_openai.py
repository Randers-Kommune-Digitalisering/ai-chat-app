import datetime
import re
import logging
import random
import time
from json import JSONDecodeError
from abc import abstractmethod
from openai import AzureOpenAI
from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import RunStatus
from azure.ai.agents.models import ListSortOrder
from azure.core.pipeline.transport import RequestsTransport
from azure.core.exceptions import ServiceRequestError
from azure.identity import DefaultAzureCredential
import urllib
import requests
import tiktoken
from requests.adapters import HTTPAdapter
from utils.extract_filedata import extract_text_from_file
from utils.config import (
    AZURE_AISEARCH_ENDPOINT,
    AZURE_AISEARCH_INDEX_NAME,
    AZURE_OPENAI_DEPLOYMENT_NAME,
    AZURE_OPENAI_DEPLOYMENT_NAME_TITLE_GENERATION,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    AZURE_API_VERSION_OPENAI,
    AZURE_AISEARCH_SEMANTIC_CONFIG,
    AZURE_AIFOUNDRY_PROJECT_NAME,

    ASSISTANT_NAME,
    ASSISTANT_TYPE,
    ASSISTANT_ID,
    ASSISTANT_ALT_ID,
    DEFAULT_TOKEN_ENCODING,
    MAX_TOKEN_LIMIT_HISTORY,
    MAX_TOKEN_LIMIT_MESSAGE,

    USE_GENERAL_KNOWLEDGE,
    EMPHASIZE_RECENT_CONTENT,
    SYSTEM_PROMPT,
    TOP_P_VALUE,
    TEMPERATURE_VALUE,
    TOP_N_DOCUMENTS,
    SEARCH_STRICTNESS,
    REQUESTS_POOL_CONNECTIONS,
    REQUESTS_POOL_MAXSIZE,
    REQUESTS_POOL_BLOCK,

    MAX_MESSAGE_LENGTH,
)

logger = logging.getLogger(__name__)
_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _safe_status_code(exc: Exception) -> int | None:
    """
    Safely extract the status code from an exception.

    :param exc: The exception to extract the status code from.
    :return: The status code if found, otherwise None.
    """
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(exc, "response", None)
    for attr in ("status_code", "status", "http_status"):
        val = getattr(response, attr, None) if response is not None else None
        if isinstance(val, int):
            return val
    return None


def _is_retryable_exception(exc: Exception) -> bool:
    """
    Determine if an exception is retryable.

    :param exc: The exception to check.
    :return: True if the exception is retryable, False otherwise.
    """
    if isinstance(exc, (ServiceRequestError, TimeoutError)):
        return True
    if isinstance(exc, JSONDecodeError):
        # Azure SDK sometimes returns a non-JSON/empty body on 5xx, which blows up
        # when the SDK tries to deserialize an error model.
        return True

    status_code = _safe_status_code(exc=exc)
    if status_code in _RETRYABLE_STATUS_CODES:
        return True

    msg = str(exc or "").lower()
    if "internal server error" in msg or "status 'internal server error'" in msg:
        return True
    if "timeout" in msg or "timed out" in msg or "temporarily" in msg:
        return True
    return False


def _error_to_user_message_and_status(exc: Exception) -> tuple[str, int]:
    """
    Convert an exception to a user-friendly message and HTTP status code.

    :param exc: The exception to convert.
    :return: A tuple containing the user-friendly message and HTTP status code.
    """
    status_code = _safe_status_code(exc=exc)

    # Default mapping
    user_status = 503 if _is_retryable_exception(exc=exc) else 500
    user_message = "Assistenten havde en midlertidig fejl. Prøv igen om lidt."

    if status_code == 429:
        return "Assistenten er travl lige nu. Prøv igen om lidt.", 429

    if status_code is not None and 400 <= status_code < 500:
        # Client/request issues — don't encourage retries.
        if status_code in (401, 403):
            return "Assistenten er ikke korrekt konfigureret. Prøv igen senere.", 503
        if status_code == 404:
            return "Der opstod en fejl med samtalen. Start en ny samtale og prøv igen.", 400
        return "Der opstod en fejl i forespørgslen. Genindlæs siden eller prøv igen senere.", 400

    # Retryable 5xx and network-type errors
    if _is_retryable_exception(exc=exc):
        return "Assistenten havde en midlertidig fejl. Prøv igen om lidt.", user_status

    return user_message, user_status


def _call_with_retries(*, operation: str, func, max_retries: int = 2, base_delay_s: float = 0.4):
    """
    Call a function with retries for retryable exceptions.

    :param operation: The name of the operation being performed.
    :param func: The function to call.
    :param max_retries: The maximum number of retries.
    :param base_delay_s: The base delay between retries in seconds.
    :return: The result of the function call.
    :raises: The last exception if all retries fail.
    """
    attempt = 0
    while True:
        try:
            return func()
        except Exception as exc:
            retryable = _is_retryable_exception(exc=exc)
            status_code = _safe_status_code(exc=exc)

            if retryable and attempt < max_retries:
                delay = base_delay_s * (2**attempt) + random.uniform(0.0, 0.25)
                logger.warning(
                    "Azure op failed (op=%s attempt=%s/%s status=%s): %s; retrying in %.2fs",
                    operation,
                    attempt + 1,
                    max_retries + 1,
                    status_code,
                    exc,
                    delay,
                )
                time.sleep(delay)
                attempt += 1
                continue

            logger.error(
                "Azure op failed (op=%s attempts=%s status=%s): %s",
                operation,
                attempt + 1,
                status_code,
                exc,
                exc_info=True,
            )
            raise


def _create_pooled_requests_session() -> requests.Session:
    """
    Create a requests session with a connection pool.

    :return: A requests session with a connection pool.
    """
    adapter = HTTPAdapter(
        pool_connections=REQUESTS_POOL_CONNECTIONS,
        pool_maxsize=REQUESTS_POOL_MAXSIZE,
        pool_block=REQUESTS_POOL_BLOCK,
        max_retries=0,
    )

    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _desanitize_metadata_value(value: str) -> str:
    """
    Desanitize a metadata value by unescaping URL-encoded characters.

    :param value: The sanitized metadata value to desanitize.
    :return: The desanitized metadata value.
    """
    return urllib.parse.unquote(value)


class AzureOpenAIClient:
    """
    Base client for interacting with Azure OpenAI, providing common functionality for both Chat and Agent implementations.
    """
    def __init__(self):
        self.client = AzureOpenAI(
            api_version=AZURE_API_VERSION_OPENAI,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
        )
        self.ai_endpoint = AZURE_OPENAI_ENDPOINT
        self.search_endpoint = AZURE_AISEARCH_ENDPOINT
        self.search_index = AZURE_AISEARCH_INDEX_NAME
        self.semantic_config = AZURE_AISEARCH_SEMANTIC_CONFIG

        self.assistant_name = ASSISTANT_NAME
        self.deployment_name = AZURE_OPENAI_DEPLOYMENT_NAME
        self.assistant_type = ASSISTANT_TYPE

        self.use_general_knowledge = USE_GENERAL_KNOWLEDGE
        self.emphasize_recent_content = EMPHASIZE_RECENT_CONTENT
        self.top_p = TOP_P_VALUE
        self.temperature = TEMPERATURE_VALUE
        self.top_n_documents = TOP_N_DOCUMENTS
        self.search_strictness = SEARCH_STRICTNESS

    def close(self) -> None:
        """
        Close any resources held by the client, such as sessions or connections.
        """
        try:
            close_fn = getattr(self.client, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass

    def get_client(self):
        """
        Get the Azure OpenAI client.

        :return: The Azure OpenAI client instance.
        """
        return self.client

    def get_system_prompt(self):
        """
        Get the system prompt for the Azure OpenAI client (only used in Chat, not Agent).

        :return: The system prompt string.
        """
        system_prompt = SYSTEM_PROMPT.strip()

        if self.emphasize_recent_content:
            weekdays_danish = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]
            now = datetime.datetime.now()
            weekday = weekdays_danish[now.weekday()]
            date = f"{weekday} d. {now.strftime('%d-%m-%Y')}"
            system_prompt = system_prompt + f"\nDagens dato er {date}, og du skal altid bruge den nyeste information, der er tilgængelig."

        return system_prompt

    @abstractmethod
    def fetch_chat_response(self, **args) -> tuple[str | None, list[dict], str | None, int]:
        """
        Fetch a chat response from the Azure OpenAI client (ChatCompletions for Chat, Agents for Agent).

        :param args: Additional arguments for the chat request.
        :return: A tuple containing the assistant response, list of referenced citations, error message (if any), and HTTP status code.
        """
        pass

    @staticmethod
    def sort_refs(match):
        refs = re.findall(r'\[(\d+)\]', match.group(0))
        sorted_refs = sorted(int(ref) for ref in refs)
        return ''.join(f'[{ref}]' for ref in sorted_refs)


class Chat(AzureOpenAIClient):
    """
    Client for handling chat interactions using Azure OpenAI ChatCompletions, including optional retrieval-augmented generation with Azure Search.
    """
    def __init__(self):
        super().__init__()

    def fetch_chat_response(self, chat_messages) -> tuple[str | None, list[dict], str | None, int]:
        """
        Fetch a chat response from Azure OpenAI ChatCompletions, optionally using Azure Search for retrieval-augmented generation.

        :param chat_messages: A list of chat messages in the conversation history, including attached files.
        :return: A tuple containing the assistant response, list of referenced citations, error message (if any), and HTTP status code.
        """
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
                        "in_scope": False if self.use_general_knowledge else True,
                        "filter": None,
                        "strictness": self.search_strictness,
                        "top_n_documents": self.top_n_documents,
                        "authentication": {
                            "type": "system_assigned_managed_identity"
                        }
                    }
                }
            ]
        } if self.search_endpoint and self.search_index and self.search_index != "" else {}

        # Add system prompt to messages
        request_messages = []
        system_prompt = {
            "role": "system",
            "content": self.get_system_prompt()
        }
        request_messages.append(system_prompt)

        # Append document text to each user message if available
        for chat_message in chat_messages:
            request_message = {
                "role": chat_message["role"],
                "content": chat_message["content"]
            }
            if chat_message.get("files") and chat_message["role"] == "user":
                request_message["content"] = f"{request_message['content']}\n\n# Der er uploadet {len(chat_message['files'])} dokument{'er' if len(chat_message['files']) > 1 else ''}. Benyt følgende indhold fra {'de uploadede dokumenter' if len(chat_message['files']) > 1 else 'det uploadede dokument'} som kontekst for forespørgslen:\n\n"
                for index, file in enumerate(chat_message["files"]):
                    doc_text = extract_text_from_file(file=file)
                    request_message["content"] = f"{request_message['content']}\n\n## Dokument {index + 1}: {file.filename}\n### Indhold:\n\n{doc_text}"
            request_messages.append(request_message)

        # Return early if message(s) exceeds maximum token length
        try:
            encoding = tiktoken.encoding_for_model(self.deployment_name)
        except KeyError:
            encoding = tiktoken.get_encoding(DEFAULT_TOKEN_ENCODING)

        message_tokens = len(encoding.encode(request_messages[-1]["content"]))
        if message_tokens > MAX_TOKEN_LIMIT_MESSAGE:
            has_files = bool(chat_messages[-1].get("files"))
            return (
                None,
                [],
                f"Din besked er for lang{', eller dine dokumenter er for store.' if has_files else '.'} Reducer længden af din besked{', eller fjern nogle dokumenter' if has_files else ''} og prøv igen.",
                400,
            )
        total_tokens = sum(
            len(encoding.encode(m.get("content", "")))
            for m in request_messages
            if isinstance(m, dict) and isinstance(m.get("content"), str)
        )
        message_length = total_tokens
        if message_length > MAX_TOKEN_LIMIT_HISTORY:
            has_files = bool(any(m.get("files") for m in chat_messages if m.get("role") == "user"))
            return (
                None,
                [],
                f"Din samtale er for lang{', eller dine dokumenter er for store.' if has_files else '.'} Overvej at starte en ny samtale.",
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
            msg, status = _error_to_user_message_and_status(exc=exc)
            return None, [], msg, status

        if not response or not hasattr(response, "choices") or len(response.choices) == 0:
            return None, [], "Der opstod en fejl ved indlæsning af assistentens svar. Prøv igen om lidt.", 502

        elif response and hasattr(response, "choices") and len(response.choices) > 0:
            choice = response.choices[0]
            assistant_response = ""

            # Map citations
            if hasattr(choice, "message") and hasattr(choice.message, "content"):
                assistant_response = choice.message.content

                # Find all citation references in the response (e.g., [doc1], [doc2], [1], [2] ...)
                citation_refs = re.findall(r'\[(?:doc)?(\d{1,2})\]', assistant_response)
                citation_refs = [int(ref) for ref in citation_refs]
                unique_refs = sorted(set(citation_refs))

                # Collect all citations from the response context
                all_citations = []
                if hasattr(choice.message, "context") and choice.message.context.get("citations"):
                    all_citations = choice.message.context.get("citations")

                # Map URLs to reference numbers
                unique_urls = set(
                    all_citations[i - 1].get('url')
                    for i in unique_refs
                    if 0 < i <= len(all_citations) and all_citations[i - 1] is not None and hasattr(all_citations[i - 1], 'get')
                )
                url_index_map = [
                    {
                        "url": self.parse_urlencoding(url),
                        "title": self.parse_urlencoding(next((c.get('title') for c in all_citations if c.get('url') == url), None)),
                        "refs": [i + 1 for i, u in enumerate(all_citations) if u and u.get('url') == url]
                    }
                    for url in unique_urls
                ]

                # Reduce citations to referenced ones only
                referenced_citations = [item for item in url_index_map if any(ref in item['refs'] for ref in unique_refs)]

                # Update titles for referenced citations only once
                for idx, item in enumerate(referenced_citations):
                    old_title = _desanitize_metadata_value(item.get('title'))
                    item["title"] = f"[{idx + 1}] {old_title}"

                # Update assistant response with new reference numbers
                def replace_ref(m):
                    orig_ref = int(m.group(1))
                    # Find the URL for this original reference
                    if 0 < orig_ref <= len(all_citations):
                        citation_url = self.parse_urlencoding(all_citations[orig_ref - 1].get('url'))

                        # Find the new reference number based on url_index_map order
                        for idx, url_info in enumerate(url_index_map):
                            if url_info['url'] == citation_url:
                                ref_number = idx + 1
                                return f"[{ref_number}]"

                    # Fallback if not found
                    return f"[{orig_ref}]"

                assistant_response = re.sub(
                    r'\[(?:doc)?(\d{1,2})\]',
                    replace_ref,
                    assistant_response
                )

                # Remove consecutive duplicate references (e.g., [1][1] -> [1])
                assistant_response = re.sub(r'(\[\d+\])(?:\1)+', r'\1', assistant_response)

                # Sort consecutive references in ascending order (e.g., [2][1] -> [1][2])
                assistant_response = re.sub(r'(\[\d+\]){2,}', self.sort_refs, assistant_response)

        return assistant_response, referenced_citations if 'referenced_citations' in locals() else [], None, 200

    def parse_urlencoding(self, s):
        """
        Decode a URL-encoded string.

        :param s: The URL-encoded string to decode.
        :return: The decoded string.
        """
        if not s:
            return s
        import urllib.parse
        return urllib.parse.unquote(s)


class Agent(AzureOpenAIClient):
    """
    Client for handling interactions with Azure OpenAI Agents (V1).
    """
    def __init__(self):
        super().__init__()
        self.assistant_id = ASSISTANT_ID
        self.assistant_alt_id = ASSISTANT_ALT_ID
        self.project_name = AZURE_AIFOUNDRY_PROJECT_NAME

        self._session = _create_pooled_requests_session()
        self._transport = RequestsTransport(session=self._session)
        self.project = AIProjectClient(
            credential=DefaultAzureCredential(),
            endpoint=f"https://sc-oai-it.services.ai.azure.com/api/projects/{self.project_name}",
            transport=self._transport,
        )
        # self.agent = self.project.agents.get_agent(self.assistant_id)

        self._closed = False

    def close(self) -> None:
        """
        Close any resources held by the client, such as sessions or connections.
        """
        if getattr(self, "_closed", False):
            return
        self._closed = True

        try:
            close_fn = getattr(self.project, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass

        try:
            transport = getattr(self, "_transport", None)
            close_fn = getattr(transport, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass

        try:
            session = getattr(self, "_session", None)
            close_fn = getattr(session, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass

        super().close()

    def fetch_chat_response(self, chat_message, files, thread_id, use_alt=False) -> tuple[str | None, list[dict], str | None, int]:
        """
        Fetch a chat response from Azure OpenAI Agents, by creating a new message and run in the specified thread,
        then retrieving the assistant's response message and any citations.

        :param chat_message: The latest user message to send to the agent.
        :param files: Optional list of files uploaded by the user, to be included as context.
        :param thread_id: The thread ID for the conversation.
        :param use_alt: Optional flag to use an alternative assistant configuration.
        :return: A tuple containing the assistant's response, any referenced citations, an error message if applicable, and the HTTP status code.
        """
        if not thread_id:
            logger.error("Thread ID is required for fetching chat response in Agent mode.")
            return None, [], "Der opstod en fejl med samtalen. Prøv at genindlæse siden, eller start en ny samtale.", 400  # Return early if thread_id is missing

        # Append document text to the last user message if available
        request_message = chat_message
        if files:
            if len(files) > 1:
                request_message = f"{request_message}\n\n# Der er uploadet {len(files)} dokumenter. Benyt følgende indhold fra de uploadede dokumenter som kontekst for forespørgslen:\n\n"
            for index, file in enumerate(files):
                doc_text = extract_text_from_file(file=file)
                request_message = f"{request_message}\n\n## Dokument {index + 1}: {file.filename}\n### Indhold:\n\n{doc_text}"

        # Return early if message exceeds maximum length
        message_length = len(request_message)
        if message_length > MAX_MESSAGE_LENGTH:
            has_files = bool(files)
            return (
                None,
                [],
                f"Din besked er for lang{', eller dine dokumenter er for store.' if has_files else '.'} Reducer længden af din besked{', eller fjern nogle dokumenter' if has_files else ''} og prøv igen.",
                400,
            )

        # Return early to avoid creating a new run if one is already active
        try:
            run_list = _call_with_retries(
                operation="agents.runs.list",
                func=lambda: self.project.agents.runs.list(thread_id=thread_id, order=ListSortOrder.DESCENDING),
            )
        except Exception as exc:
            msg, status = _error_to_user_message_and_status(exc=exc)
            return None, [], msg, status

        if any(run.status in [RunStatus.QUEUED.value, RunStatus.IN_PROGRESS.value, RunStatus.REQUIRES_ACTION.value, RunStatus.CANCELLING.value] for run in run_list):
            logger.error(f"A run is already active for thread_id {thread_id}. Cannot start a new run until the current one finishes.")
            return None, [], "Assistenten er allerede ved at svare på denne samtale. Prøv at genindlæse siden, eller start en ny samtale.", 409

        try:
            # Avoid retrying message creation to prevent duplicate user messages.
            self.project.agents.messages.create(
                thread_id=thread_id,
                role="user",
                content=request_message,
            )
        except Exception as exc:
            msg, status = _error_to_user_message_and_status(exc=exc)
            return None, [], msg, status

        def _create_run_once():
            return self.project.agents.runs.create_and_process(
                thread_id=thread_id,
                agent_id=self.assistant_id if not use_alt else self.assistant_alt_id,
            )

        try:
            # Retry transient 5xx/429/etc. If a run actually started, don't create a second run.
            try:
                run = _create_run_once()
            except Exception as exc:
                if _is_retryable_exception(exc=exc):
                    try:
                        run_list_after = self.project.agents.runs.list(thread_id=thread_id, order=ListSortOrder.DESCENDING)
                        if any(
                            r.status in [RunStatus.QUEUED.value, RunStatus.IN_PROGRESS.value, RunStatus.REQUIRES_ACTION.value, RunStatus.CANCELLING.value]
                            for r in run_list_after
                        ):
                            return (
                                None,
                                [],
                                "Assistenten er ved at behandle din besked. Prøv at genindlæse siden om lidt.",
                                409,
                            )
                    except Exception:
                        pass
                raise
        except Exception as exc:
            msg, status = _error_to_user_message_and_status(exc=exc)
            return None, [], msg, status

        if run.status == "failed":
            logger.error(f"Run failed: {run.last_error}")
            return None, [], "Der opstod en fejl ved indlæsning af assistentens svar. Prøv at genindlæse siden, eller start en ny samtale.", 503
        else:
            try:
                messages = _call_with_retries(
                    operation="agents.messages.list",
                    func=lambda: self.project.agents.messages.list(thread_id=thread_id, order=ListSortOrder.DESCENDING),
                )
            except Exception as exc:
                msg, status = _error_to_user_message_and_status(exc=exc)
                return None, [], msg, status

        assistant_message = next(  # Find the latest assistant message in the thread
            (
                msg for msg in messages
                if getattr(msg, "role", None) == "assistant"
                and getattr(msg, "content", None)
                and any(
                    getattr(content_block, "type", None) == "text"
                    and hasattr(getattr(content_block, "text", None), "value")
                    for content_block in msg.content
                )
            ),
            None
        )

        text_value = ""
        annotations = []
        citations = []

        # Loop content blocks to extract assistant response and citations
        if assistant_message:
            for content_block in assistant_message.content:
                # Extract the text value from the first content block of type 'text'
                if getattr(content_block, "type", None) == "text":
                    text_obj = getattr(content_block, "text", None)
                    if text_obj and hasattr(text_obj, "value"):
                        text_value = text_obj.value
                        if hasattr(text_obj, "annotations"):
                            annotations = text_obj.annotations
                        break

            for annotation in annotations:
                citation = dict(annotation.get("url_citation", {}))
                citation["replace_refs"] = annotation.get("text", "")
                citation["title"] = _desanitize_metadata_value(citation.get("title", ""))

                # Find the index of the citation URL in the unique list of annotation URLs
                citation["refs"] = [i + 1 for i, a in enumerate(annotations) if a.get("url_citation") and a.get("url_citation").get("url") == citation.get("url")]

                if citation not in citations:
                    citations.append(citation)

                text_value = text_value.replace(citation["replace_refs"], "")  # Remove original ref from response text

        else:
            logger.error(
                "No assistant text message returned for thread_id %s (run status=%s)",
                thread_id,
                getattr(run, "status", None),
            )
            return None, [], "Der opstod en fejl ved indlæsning af assistentens svar. Prøv at genindlæse siden, eller start en ny samtale.", 502

        return text_value, citations, None, 200

    def create_thread(self) -> str:
        """
        Create a new thread for the Agent conversation.'

        :return: The string ID of the newly created thread.
        """
        thread = _call_with_retries(
            operation="agents.threads.create",
            func=lambda: self.project.agents.threads.create(),
            max_retries=2,
        )
        return thread.id


class AzureOpenAITitleGenerator():
    def __init__(self):
        self.client = AzureOpenAI(
            api_version=AZURE_API_VERSION_OPENAI,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
        )
        self.deployment_name = AZURE_OPENAI_DEPLOYMENT_NAME_TITLE_GENERATION

    def generate_title(self, conversation_messages):
        """
        Generate a short title for a conversation based on the user's first message.

        :param conversation_messages: A list of messages in the conversation.
        :return: A string containing the generated title.
        """
        system_prompt = {
            "role": "system",
            "content": "Du er en hjælpsom assistent, der genererer korte og præcise titler (maksimalt 24 tegn) til samtaler baseret på brugerens første besked. Titlen skal være på dansk og opsummere samtalens emne uden at inkludere citater eller referencer."
        }
        user_prompt = {
            "role": "user",
            "content": f"Generer en kort titel for følgende besked: '{conversation_messages[0]['content']}'"
        }

        response = self.client.chat.completions.create(
            messages=[system_prompt, user_prompt],
            temperature=0.5,
            top_p=0.9,
            model=self.deployment_name
        )

        if response and hasattr(response, "choices") and len(response.choices) > 0:
            choice = response.choices[0]
            if hasattr(choice, "message") and hasattr(choice.message, "content"):
                title = choice.message.content.strip().strip('"').strip("'")
                return title

        return "Ny samtale"  # Fallback title


def get_chat_client() -> AzureOpenAIClient:
    """
    Get the appropriate Azure OpenAI client based on the assistant type.

    :return: An instance of AzureOpenAIClient (either Agent or Chat).
    """
    if ASSISTANT_TYPE.lower() == "agent":
        return Agent()
    return Chat()


def get_title_generator() -> AzureOpenAITitleGenerator:
    """
    Get the Azure OpenAI client for title generation.

    :return: An instance of AzureOpenAITitleGenerator.
    """
    return AzureOpenAITitleGenerator()
