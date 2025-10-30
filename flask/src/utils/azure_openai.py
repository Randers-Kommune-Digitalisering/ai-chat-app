import datetime
import re
from openai import AzureOpenAI
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import ListSortOrder
from utils.extract_filedata import extract_text_from_file

from utils.config import (
    AZURE_AISEARCH_ENDPOINT,
    AZURE_AISEARCH_INDEX_NAME,
    AZURE_OPENAI_DEPLOYMENT_NAME,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    AZURE_API_VERSION_OPENAI,
    AZURE_AISEARCH_SEMANTIC_CONFIG,
    AZURE_AIFOUNDRY_PROJECT_NAME,

    ASSISTANT_NAME,
    ASSISTANT_TYPE,
    ASSISTANT_ID,

    USE_GENERAL_KNOWLEDGE,
    EMPHASIZE_RECENT_CONTENT,
    SYSTEM_PROMPT,
    TOP_P_VALUE,
    TEMPERATURE_VALUE,
    TOP_N_DOCUMENTS,
    SEARCH_STRICTNESS
)


def get_chat_client():
    if ASSISTANT_TYPE.lower() == "agent":
        return Agent()
    return Chat()


class AzureOpenAIClient:
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

    def get_client(self):
        return self.client

    def get_system_prompt(self):
        system_prompt = SYSTEM_PROMPT.strip()

        if self.emphasize_recent_content:
            weekdays_danish = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]
            now = datetime.datetime.now()
            weekday = weekdays_danish[now.weekday()]
            date = f"{weekday} d. {now.strftime('%d-%m-%Y')}"
            system_prompt = system_prompt + f"\nDagens dato er {date}, og du skal altid bruge den nyeste information, der er tilgængelig."

        return system_prompt

    @staticmethod
    def sort_refs(match):
        refs = re.findall(r'\[(\d+)\]', match.group(0))
        sorted_refs = sorted(int(ref) for ref in refs)
        return ''.join(f'[{ref}]' for ref in sorted_refs)


class Chat(AzureOpenAIClient):  # TODO: Fix method signature to match Agent
    def __init__(self):
        super().__init__()

    def fetch_chat_response(self, thread_id, chat_messages, files):
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

        # Append document text to user messages if available
        request_messages = []
        for message in chat_messages:
            request_message = {
                "role": message["role"],
                "content": message["content"]
            }
            if message.get("doc_text"):
                request_message["content"] = f"{request_message['content']}\n\nBenyt følgende indhold fra uploaded dokument som kontekst for forespørgslen:\n\n{message['doc_text']}"
            request_messages.append(request_message)

        response = self.client.chat.completions.create(
            messages=request_messages,
            temperature=self.temperature,
            top_p=self.top_p,
            model=self.deployment_name,
            extra_body=ai_search_body
        )

        if response and hasattr(response, "choices") and len(response.choices) > 0:
            choice = response.choices[0]
            assistant_response = ""

            # Map citations
            if hasattr(choice, "message") and hasattr(choice.message, "content"):
                assistant_response = choice.message.content

                # 1. Find all citation references in the response (e.g., [doc1], [doc2], [1], [2] ...)
                citation_refs = re.findall(r'\[(?:doc)?(\d{1,2})\]', assistant_response)
                citation_refs = [int(ref) for ref in citation_refs]
                unique_refs = sorted(set(citation_refs))

                # 2. Collect all citations from the response context
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
                        "url": url,
                        "title": next((c.get('title') for c in all_citations if c.get('url') == url), None),
                        "refs": [i + 1 for i, u in enumerate(all_citations) if u and u.get('url') == url]
                    }
                    for url in unique_urls
                ]

                # Reduce citations to referenced ones only
                referenced_citations = [item for item in url_index_map if any(ref in item['refs'] for ref in unique_refs)]

                # Update assistant response with new reference numbers
                assistant_response = re.sub(
                    r'\[(?:doc)?(\d{1,2})\]',
                    lambda m: (
                        f"[{next((i + 1 for i, url_info in enumerate(url_index_map) if (0 < int(m.group(1)) <= len(all_citations)) and all_citations[int(m.group(1)) - 1] is not None and all_citations[int(m.group(1)) - 1].get('url') == url_info['url']), '?')}]"
                    ),
                    assistant_response
                )

                # Remove consecutive duplicate references (e.g., [1][1] -> [1])
                assistant_response = re.sub(r'(\[\d+\])(?:\1)+', r'\1', assistant_response)

                # Sort consecutive references in ascending order (e.g., [2][1] -> [1][2])
                assistant_response = re.sub(r'(\[\d+\]){2,}', self.sort_refs, assistant_response)

        return {"role": "assistant", "content": assistant_response}, referenced_citations


class Agent(Chat):
    def __init__(self):
        super().__init__()
        self.assistant_id = ASSISTANT_ID
        self.project_name = AZURE_AIFOUNDRY_PROJECT_NAME
        self.project = AIProjectClient(
            credential=DefaultAzureCredential(),
            endpoint=f"https://sc-oai-it.services.ai.azure.com/api/projects/{self.project_name}"
        )
        self.agent = self.project.agents.get_agent(self.assistant_id)

    def fetch_chat_response(self, thread_id, chat_message, files):
        if not thread_id:
            return {"role": "assistant", "content": "Error: No thread_id provided for Agent. Please create a thread first."}, []

        # Append document text to the last user message if available
        request_message = chat_message
        if files:
            if len(files) > 1:
                request_message = f"{request_message}\n\n# Der er uploadet {len(files)} dokumenter. Benyt følgende indhold fra de uploadede dokumenter som kontekst for forespørgslen:\n\n"
            for index, file in enumerate(files):
                doc_text = extract_text_from_file(file)
                request_message = f"{request_message}\n\n## Dokument {index + 1}: {file.filename}\n### Indhold:\n\n{doc_text}"

        self.project.agents.messages.create(
            thread_id=thread_id,
            role="user",
            content=request_message
        )
        run = self.project.agents.runs.create_and_process(
            thread_id=thread_id,
            agent_id=self.assistant_id
        )
        if run.status == "failed":
            print(f"Run failed: {run.last_error}")
            return None, []
        else:
            messages = self.project.agents.messages.list(thread_id=thread_id, order=ListSortOrder.DESCENDING)

        assistant_message = next(  # Find the latest assistant message in the thread
            (
                msg for msg in messages
                if getattr(msg, "role", None) == "assistant"
                and getattr(msg, "content", None)
                and any(
                    getattr(content_block, "type", None) == "text" and
                    hasattr(getattr(content_block, "text", None), "value")
                    for content_block in msg.content
                )
            ),
            None
        )

        text_value = ""
        annotations = []
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

            citations = []
            for annotation in annotations:
                citation = dict(annotation.get("url_citation", {}))
                citation["replace_refs"] = annotation.get("text", "")

                # Find the index of the citation URL in the unique list of annotation URLs
                citation["refs"] = [i + 1 for i, a in enumerate(annotations) if a.get("url_citation") and a.get("url_citation").get("url") == citation.get("url")]

                if citation not in citations:
                    citations.append(citation)

                for ref in citation["refs"]:
                    text_value = text_value.replace(citation["replace_refs"], f" [{ref}]")

        # Remove spaces between consecutive references (e.g., [1] [2] [3] -> [1][2][3])
        text_value = re.sub(r'(\[\d+\](?:\s+\[\d+\])+)', lambda m: re.sub(r'\s+', '', m.group(0)), text_value)

        # Sort consecutive references in ascending order (e.g., [2][1] -> [1][2])
        text_value = re.sub(r'(\[\d+\]){2,}', self.sort_refs, text_value)

        return text_value, citations

    def create_thread(self):
        thread = self.project.agents.threads.create()
        return thread.id
