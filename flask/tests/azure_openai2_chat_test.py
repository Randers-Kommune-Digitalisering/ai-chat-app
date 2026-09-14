from types import SimpleNamespace

import utils.azure_openai2 as azure_openai2


class _FakeEncoding:
    def encode(self, value):
        return list(value)


class _FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _build_chat(response):
    chat = azure_openai2.Chat.__new__(azure_openai2.Chat)
    chat.client = SimpleNamespace(
        chat=SimpleNamespace(completions=_FakeCompletions(response))
    )
    chat.search_endpoint = "https://search.example.com"
    chat.search_index = "documents"
    chat.semantic_config = "default"
    chat.use_general_knowledge = False
    chat.emphasize_recent_content = False
    chat.top_p = 0.8
    chat.temperature = 0.2
    chat.top_n_documents = 5
    chat.search_strictness = 3
    chat.deployment_name = "deployment"
    return chat


def test_chat_fetch_uses_legacy_chat_completions_and_maps_citations(monkeypatch):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="Svar [doc2][doc2][doc1]",
                    context={
                        "citations": [
                            {"url": "https%3A//example.com/a", "title": "Wikipedia%20-%20Randers"},
                            {"url": "https%3A//example.com/b", "title": "Google%20%26%20Maps"},
                        ]
                    },
                )
            )
        ]
    )
    chat = _build_chat(response)
    monkeypatch.setattr(azure_openai2, "_get_token_encoding", lambda _model: _FakeEncoding())

    text, references, error, status = chat.fetch_chat_response(
        chat_messages=[{"role": "user", "content": "Hej", "files": []}]
    )

    request = chat.client.chat.completions.kwargs
    assert request["messages"] == [
        {"role": "system", "content": azure_openai2.SYSTEM_PROMPT},
        {"role": "user", "content": "Hej"},
    ]
    assert request["extra_body"]["data_sources"][0]["type"] == "azure_search"
    assert text == (
        'Svar <span class="inline-reference">[Wikipedia - Randers]</span>'
        '<span class="inline-reference">[Google &amp; Maps]</span>'
    )
    assert references == [
        {
            "type": "url_citation",
            "url": "https://example.com/a",
            "title": "Wikipedia - Randers",
            "refs": [1],
        },
        {
            "type": "url_citation",
            "url": "https://example.com/b",
            "title": "Google & Maps",
            "refs": [2],
        },
    ]
    assert error is None
    assert status == 200


def test_get_chat_client_selects_legacy_chat(monkeypatch):
    expected = object()
    monkeypatch.setattr(azure_openai2, "ASSISTANT_TYPE", "chat")
    monkeypatch.setattr(azure_openai2, "Chat", lambda: expected)

    assert azure_openai2.get_chat_client() is expected
