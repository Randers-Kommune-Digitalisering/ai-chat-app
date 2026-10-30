from http.client import IncompleteRead
from types import SimpleNamespace

import utils.azure_openai as azure_openai
from utils.azure_openai import Agent, _extract_native_annotations_from_stream_event, _status_for_stream_event


def test_status_for_stream_event_maps_reasoning_search_and_output_text_without_event_details():
    cases = [
        (
            SimpleNamespace(type="response.output_item.done", item=SimpleNamespace(type="reasoning")),
            {"status": "thinking", "message": "Assistenten tænker ..."},
        ),
        (
            SimpleNamespace(type="response.output_item.added", item=SimpleNamespace(type="web_search_call")),
            {"status": "web_search", "message": "Assistenten søger på nettet ..."},
        ),
        (
            SimpleNamespace(type="response.output_item.added", item=SimpleNamespace(type="bing_grounding_call")),
            {"status": "web_search", "message": "Assistenten søger på nettet ..."},
        ),
        (
            SimpleNamespace(type="response.content_part.added", part=SimpleNamespace(type="output_text")),
            {"status": "answering", "message": "Assistenten svarer ..."},
        ),
    ]

    for event, expected in cases:
        assert _status_for_stream_event(event) == expected


def test_stream_chat_response_with_metadata_deduplicates_status_events():
    events = [
        SimpleNamespace(type="response.output_item.added", item=SimpleNamespace(type="reasoning")),
        SimpleNamespace(type="response.output_item.done", item=SimpleNamespace(type="reasoning")),
        SimpleNamespace(type="response.output_text.delta", delta="Svar"),
        SimpleNamespace(type="response.output_text.delta", delta=" mere"),
    ]

    class _FakeResponses:
        def create(self, **kwargs):
            return iter(events)

    agent = Agent.__new__(Agent)
    agent.client = SimpleNamespace(responses=_FakeResponses())
    agent._resolve_agent_reference = lambda use_alt: {"name": "agent_1", "type": "agent_reference"}
    agent._prepare_response_input = lambda chat_message, files: [{"role": "user", "content": []}]

    emitted = list(agent.stream_chat_response_with_metadata("Hej", [], "conv_status"))

    assert [event for event in emitted if event["type"] == "status"] == [
        {"type": "status", "status": "thinking", "message": "Assistenten tænker ..."},
        {"type": "status", "status": "answering", "message": "Assistenten svarer ..."},
    ]


def test_extract_native_annotations_from_response_completed_event_handles_nested_shapes():
    event = SimpleNamespace(
        type="response.completed",
        response=SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="message",
                    content=[
                        SimpleNamespace(
                            type="output_text",
                            annotations=[
                                {
                                    "url_citation": {
                                        "title": "Nested URL",
                                        "url": "https://example.com/nested",
                                    }
                                },
                                {
                                    "container_file_citation": {
                                        "filename": "budget.xlsx",
                                        "file_id": "file_2",
                                    }
                                },
                            ],
                        )
                    ],
                )
            ]
        ),
    )

    refs = _extract_native_annotations_from_stream_event(event=event)

    assert refs is not None
    assert len(refs) == 2
    assert refs[0] == {
        "url_citation": {
            "title": "Nested URL",
            "url": "https://example.com/nested",
        }
    }
    assert refs[1] == {
        "container_file_citation": {
            "filename": "budget.xlsx",
            "file_id": "file_2",
        }
    }


def test_extract_native_annotations_from_annotation_added_event():
    event = SimpleNamespace(
        type="response.output_text.annotation.added",
        annotation={
            "type": "url_citation",
            "title": "Randers Wiki",
            "url": "https://da.wikipedia.org/wiki/Randers",
        },
    )

    refs = _extract_native_annotations_from_stream_event(event=event)

    assert refs is not None
    assert len(refs) == 1
    assert refs[0] == {
        "type": "url_citation",
        "title": "Randers Wiki",
        "url": "https://da.wikipedia.org/wiki/Randers",
    }


def test_stream_chat_response_with_metadata_uses_streamed_annotations_when_completed_has_none():
    events = [
        SimpleNamespace(type="response.output_text.delta", delta="Svar "),
        SimpleNamespace(
            type="response.output_text.annotation.added",
            annotation={
                "type": "url_citation",
                "title": "Randers Wiki",
                "url": "https://da.wikipedia.org/wiki/Randers",
            },
        ),
        SimpleNamespace(
            type="response.output_text.annotation.added",
            annotation={
                "type": "url_citation",
                "title": "Kommune",
                "url": "https://www.randers.dk",
            },
        ),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", annotations=[])],
                    )
                ]
            ),
        ),
    ]

    class _FakeResponses:
        def __init__(self, stream_events):
            self._events = stream_events

        def create(self, **kwargs):
            return iter(self._events)

    class _FakeClient:
        def __init__(self, stream_events):
            self.responses = _FakeResponses(stream_events)

    agent = Agent.__new__(Agent)
    agent.client = _FakeClient(events)
    agent._resolve_agent_reference = lambda use_alt: {"name": "agent_1", "type": "agent_reference"}
    agent._prepare_response_input = lambda chat_message, files: [{"role": "user", "content": []}]

    emitted = list(
        agent.stream_chat_response_with_metadata(
            chat_message="Hej",
            files=[],
            thread_id="conv_1",
            use_alt=False,
        )
    )

    assert next(event for event in emitted if event["type"] == "delta") == {"type": "delta", "text": "Svar "}
    assert emitted[-1]["type"] == "references"
    assert emitted[-1]["references"] == [
        {
            "type": "url_citation",
            "title": "Randers Wiki",
            "url": "https://da.wikipedia.org/wiki/Randers",
        },
        {
            "type": "url_citation",
            "title": "Kommune",
            "url": "https://www.randers.dk",
        },
    ]


def test_stream_chat_response_with_metadata_keeps_annotations_missing_from_partial_snapshot():
    first_reference = {
        "type": "url_citation",
        "title": "Randers Wiki",
        "url": "https://da.wikipedia.org/wiki/Randers",
    }
    second_reference = {
        "type": "url_citation",
        "title": "Kommune",
        "url": "https://www.randers.dk",
    }
    events = [
        SimpleNamespace(type="response.output_text.annotation.added", annotation=first_reference),
        SimpleNamespace(type="response.output_text.annotation.added", annotation=second_reference),
        SimpleNamespace(
            type="response.content_part.done",
            part=SimpleNamespace(type="output_text", annotations=[second_reference]),
        ),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(output=[]),
        ),
    ]

    class _FakeResponses:
        def create(self, **kwargs):
            return iter(events)

    agent = Agent.__new__(Agent)
    agent.client = SimpleNamespace(responses=_FakeResponses())
    agent._resolve_agent_reference = lambda use_alt: {"name": "agent_1", "type": "agent_reference"}
    agent._prepare_response_input = lambda chat_message, files: [{"role": "user", "content": []}]

    emitted = list(agent.stream_chat_response_with_metadata("Hej", [], "conv_partial_snapshot"))

    assert emitted[-1] == {
        "type": "references",
        "references": [first_reference, second_reference],
    }


def test_extract_native_annotations_from_response_completed_uses_web_search_sources_when_no_annotations():
    event = SimpleNamespace(
        type="response.completed",
        response=SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="web_search_call",
                    action=SimpleNamespace(
                        type="search",
                        query="Randers",
                        sources=[
                            SimpleNamespace(type="url", url="https://da.wikipedia.org/wiki/Randers"),
                            SimpleNamespace(type="url", url="https://www.randers.dk"),
                        ],
                    ),
                ),
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(type="output_text", annotations=[])],
                ),
            ]
        ),
    )

    refs = _extract_native_annotations_from_stream_event(event=event)

    assert refs == [
        {
            "type": "url_citation",
            "title": "https://da.wikipedia.org/wiki/Randers",
            "url": "https://da.wikipedia.org/wiki/Randers",
        },
        {
            "type": "url_citation",
            "title": "https://www.randers.dk",
            "url": "https://www.randers.dk",
        },
    ]


def test_extract_native_annotations_from_output_item_done_uses_web_search_sources():
    event = SimpleNamespace(
        type="response.output_item.done",
        item=SimpleNamespace(
            type="web_search_call",
            action=SimpleNamespace(
                type="open_page",
                url="https://www.randers.dk",
            ),
        ),
    )

    refs = _extract_native_annotations_from_stream_event(event=event)

    assert refs == [
        {
            "type": "url_citation",
            "title": "https://www.randers.dk",
            "url": "https://www.randers.dk",
        }
    ]


def test_extract_native_annotations_from_output_item_added_uses_web_search_sources():
    event = SimpleNamespace(
        type="response.output_item.added",
        item=SimpleNamespace(
            type="web_search_call",
            action=SimpleNamespace(
                type="search",
                sources=[
                    SimpleNamespace(type="url", url="https://da.wikipedia.org/wiki/Randers"),
                ],
            ),
        ),
    )

    refs = _extract_native_annotations_from_stream_event(event=event)

    assert refs == [
        {
            "type": "url_citation",
            "title": "https://da.wikipedia.org/wiki/Randers",
            "url": "https://da.wikipedia.org/wiki/Randers",
        }
    ]


def test_extract_native_annotations_from_bing_grounding_output_uses_nested_web_results():
    event = SimpleNamespace(
        type="response.output_item.done",
        item=SimpleNamespace(
            type="bing_grounding_call_output",
            output={
                "webPages": {
                    "value": [
                        {
                            "name": "Hvidsten Kro",
                            "url": "https://da.wikipedia.org/wiki/Hvidsten_Kro",
                            "snippet": "Not returned to the frontend",
                        }
                    ]
                }
            },
        ),
    )

    assert _extract_native_annotations_from_stream_event(event) == [
        {
            "type": "url_citation",
            "title": "Hvidsten Kro",
            "url": "https://da.wikipedia.org/wiki/Hvidsten_Kro",
        }
    ]


def test_status_for_bing_grounding_call_reports_web_search():
    event = SimpleNamespace(
        type="response.output_item.added",
        item=SimpleNamespace(type="bing_grounding_call"),
    )

    assert _status_for_stream_event(event) == {
        "status": "web_search",
        "message": "Assistenten søger på nettet ...",
    }


def test_stream_preserves_bing_grounding_references_when_completed_has_no_annotations():
    events = [
        SimpleNamespace(type="response.output_item.added", item=SimpleNamespace(type="bing_grounding_call")),
        SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(
                type="bing_grounding_call_output",
                output={
                    "webPages": {
                        "value": [
                            {
                                "name": "Hvidsten Kro",
                                "url": "https://da.wikipedia.org/wiki/Hvidsten_Kro",
                            }
                        ]
                    }
                },
            ),
        ),
        SimpleNamespace(type="response.output_text.delta", delta="Svar cite8:0†source"),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", annotations=[])],
                    )
                ]
            ),
        ),
    ]

    class _FakeResponses:
        def create(self, **kwargs):
            return iter(events)

    agent = Agent.__new__(Agent)
    agent.client = SimpleNamespace(responses=_FakeResponses())
    agent._resolve_agent_reference = lambda use_alt: {"name": "agent_1", "type": "agent_reference"}
    agent._prepare_response_input = lambda chat_message, files: [{"role": "user", "content": []}]

    emitted = list(agent.stream_chat_response_with_metadata("Hej", [], "conv_bing"))

    assert emitted[-1] == {
        "type": "references",
        "references": [
            {
                "type": "url_citation",
                "title": "Hvidsten Kro",
                "url": "https://da.wikipedia.org/wiki/Hvidsten_Kro",
            }
        ],
    }


def test_stream_chat_response_with_metadata_emits_refs_from_output_item_added_when_completed_empty():
    events = [
        SimpleNamespace(type="response.output_text.delta", delta="Svar "),
        SimpleNamespace(
            type="response.output_item.added",
            item=SimpleNamespace(
                type="web_search_call",
                action=SimpleNamespace(
                    type="search",
                    sources=[
                        SimpleNamespace(type="url", url="https://da.wikipedia.org/wiki/Randers"),
                    ],
                ),
            ),
        ),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", annotations=[])],
                    )
                ]
            ),
        ),
    ]

    class _FakeResponses:
        def __init__(self, stream_events):
            self._events = stream_events

        def create(self, **kwargs):
            return iter(self._events)

    class _FakeClient:
        def __init__(self, stream_events):
            self.responses = _FakeResponses(stream_events)

    agent = Agent.__new__(Agent)
    agent.client = _FakeClient(events)
    agent._resolve_agent_reference = lambda use_alt: {"name": "agent_1", "type": "agent_reference"}
    agent._prepare_response_input = lambda chat_message, files: [{"role": "user", "content": []}]

    emitted = list(
        agent.stream_chat_response_with_metadata(
            chat_message="Hej",
            files=[],
            thread_id="conv_2",
            use_alt=False,
        )
    )

    assert next(event for event in emitted if event["type"] == "delta") == {"type": "delta", "text": "Svar "}
    assert emitted[-1] == {
        "type": "references",
        "references": [
            {
                "type": "url_citation",
                "title": "https://da.wikipedia.org/wiki/Randers",
                "url": "https://da.wikipedia.org/wiki/Randers",
            }
        ],
    }


def test_extract_ai_search_get_urls_from_stream_event_reads_get_urls_list():
    get_url = (
        "https://we-aisearch-it.search.windows.net/indexes/aisearch-randersdk-index/docs/doc_1"
        "?api-version=2024-07-01"
    )
    event = SimpleNamespace(
        type="response.output_item.done",
        item=SimpleNamespace(
            type="azure_ai_search_call_output",
            output={
                "documents": [],
                "get_urls": [get_url],
            },
        ),
    )

    assert azure_openai._extract_ai_search_get_urls_from_stream_event(event=event) == [get_url]


def test_extract_ai_search_get_urls_from_completed_event_uses_latest_call_result_set():
    first_group = ["https://we-aisearch-it.search.windows.net/docs/first"]
    latest_group = ["https://we-aisearch-it.search.windows.net/docs/latest"]
    event = SimpleNamespace(
        type="response.completed",
        response=SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="azure_ai_search_call_output",
                    output={"get_urls": first_group},
                ),
                SimpleNamespace(
                    type="azure_ai_search_call_output",
                    output={"get_urls": latest_group},
                ),
            ],
        ),
    )

    assert azure_openai._extract_ai_search_get_urls_from_stream_event(event=event) == latest_group


def test_extract_ai_search_get_urls_from_completed_event_preserves_latest_empty_result_set():
    event = SimpleNamespace(
        type="response.completed",
        response=SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="azure_ai_search_call_output",
                    output={"get_urls": ["https://we-aisearch-it.search.windows.net/docs/previous"]},
                ),
                SimpleNamespace(
                    type="azure_ai_search_call_output",
                    output={"get_urls": []},
                ),
            ],
        ),
    )

    assert azure_openai._extract_ai_search_get_urls_from_stream_event(event=event) == []


def test_normalize_ai_search_get_url_sets_select_to_title_and_url():
    input_url = (
        "https://we-aisearch-it.search.windows.net/indexes/aisearch-randersdk-index/docs/doc_1"
        "?api-version=2024-07-01&$select=id,content,title"
    )

    normalized = azure_openai._normalize_ai_search_get_url(input_url)
    parsed = azure_openai.urllib.parse.urlparse(normalized)
    query = azure_openai.urllib.parse.parse_qs(parsed.query)

    assert query["$select"] == ["title,url"]
    assert query["api-version"] == ["2024-07-01"]


def test_fetch_ai_search_document_metadata_blocks_cross_domain_urls(monkeypatch):
    monkeypatch.setattr(azure_openai, "AZURE_AISEARCH_API_KEY", "dummy-key")
    monkeypatch.setattr(
        azure_openai,
        "AZURE_AISEARCH_ENDPOINT",
        "https://we-aisearch-it.search.windows.net",
    )

    def _unexpected_urlopen(*args, **kwargs):
        raise AssertionError("urlopen should not be called for cross-domain URL")

    monkeypatch.setattr(azure_openai, "urlopen", _unexpected_urlopen)

    metadata = azure_openai._fetch_ai_search_document_metadata(
        get_url="https://evil.example.com/indexes/docs/doc_1?api-version=2024-07-01",
    )

    assert metadata is None


def test_fetch_ai_search_document_metadata_keeps_truncated_response_nonfatal(monkeypatch):
    monkeypatch.setattr(azure_openai, "AZURE_AISEARCH_API_KEY", "dummy-key")
    monkeypatch.setattr(
        azure_openai,
        "AZURE_AISEARCH_ENDPOINT",
        "https://we-aisearch-it.search.windows.net",
    )
    monkeypatch.setattr(
        azure_openai,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(IncompleteRead(b"partial response")),
    )

    metadata = azure_openai._fetch_ai_search_document_metadata(
        get_url="https://we-aisearch-it.search.windows.net/indexes/docs/doc_1",
    )

    assert metadata is None


def test_stream_chat_response_with_metadata_remaps_internal_ai_search_urls(monkeypatch):
    get_url = (
        "https://we-aisearch-it.search.windows.net/indexes/aisearch-randersdk-index/docs/doc_1"
        "?api-version=2024-07-01&$select=id,title"
    )
    public_url = "https://www.randers.dk/borger/fritid/discgolf"
    answer = "Svar \u30105:0\u2020source\u3011"

    events = [
        SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(
                type="azure_ai_search_call_output",
                output={"get_urls": [get_url]},
            ),
        ),
        SimpleNamespace(type="response.output_text.delta", delta=answer),
        SimpleNamespace(
            type="response.output_text.annotation.added",
            annotation={
                "type": "url_citation",
                "title": "Discgolf%20-%20Randers%20Kommune",
                "url": "https://we-aisearch-it.search.windows.net/",
                "start_index": answer.index("\u3010"),
                "end_index": len(answer),
            },
        ),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", annotations=[])],
                    )
                ]
            ),
        ),
    ]

    class _FakeResponses:
        def __init__(self, stream_events):
            self._events = stream_events

        def create(self, **kwargs):
            return iter(self._events)

    agent = Agent.__new__(Agent)
    agent.client = SimpleNamespace(responses=_FakeResponses(events))
    agent._resolve_agent_reference = lambda use_alt: {"name": "agent_1", "type": "agent_reference"}
    agent._prepare_response_input = lambda chat_message, files: [{"role": "user", "content": []}]

    monkeypatch.setattr(
        azure_openai,
        "_fetch_ai_search_document_metadata",
        lambda get_url, timeout_s=5.0: {
            "title": "Discgolf%20-%20Randers%20Kommune",
            "url": public_url,
        },
    )

    emitted = list(agent.stream_chat_response_with_metadata("Hej", [], "conv_ai_search"))

    assert emitted[-1] == {
        "type": "references",
        "references": [
            {
                "type": "url_citation",
                "title": "Discgolf%20-%20Randers%20Kommune",
                "url": public_url,
                "start_index": answer.index("\u3010"),
                "end_index": len(answer),
            }
        ],
    }


def test_stream_chat_response_with_metadata_decodes_encoded_metadata_url(monkeypatch):
    get_url = (
        "https://we-aisearch-it.search.windows.net/indexes/aisearch-randersdk-index/docs/doc_1"
        "?api-version=2024-07-01&$select=id,title"
    )
    encoded_public_url = (
        "https%3A%2F%2Fwww.randers.dk%2Fborger%2Ffritid%2Ffaelles-indsatser%2F"
        "bevaeg-dig-randers%2Faktiviteter%2Foplevelser-og-bevaegelse-i-det-fri%2Fdiscgolf%2F"
    )
    decoded_public_url = (
        "https://www.randers.dk/borger/fritid/faelles-indsatser/"
        "bevaeg-dig-randers/aktiviteter/oplevelser-og-bevaegelse-i-det-fri/discgolf/"
    )
    answer = "Svar \u30105:0\u2020source\u3011"

    events = [
        SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(
                type="azure_ai_search_call_output",
                output={"get_urls": [get_url]},
            ),
        ),
        SimpleNamespace(type="response.output_text.delta", delta=answer),
        SimpleNamespace(
            type="response.output_text.annotation.added",
            annotation={
                "type": "url_citation",
                "title": "Discgolf%20-%20Randers%20Kommune",
                "url": "https://we-aisearch-it.search.windows.net/",
                "start_index": answer.index("\u3010"),
                "end_index": len(answer),
            },
        ),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", annotations=[])],
                    )
                ]
            ),
        ),
    ]

    class _FakeResponses:
        def __init__(self, stream_events):
            self._events = stream_events

        def create(self, **kwargs):
            return iter(self._events)

    agent = Agent.__new__(Agent)
    agent.client = SimpleNamespace(responses=_FakeResponses(events))
    agent._resolve_agent_reference = lambda use_alt: {"name": "agent_1", "type": "agent_reference"}
    agent._prepare_response_input = lambda chat_message, files: [{"role": "user", "content": []}]

    monkeypatch.setattr(
        azure_openai,
        "_fetch_ai_search_document_metadata",
        lambda get_url, timeout_s=5.0: {
            "title": "Discgolf%20-%20Randers%20Kommune",
            "url": encoded_public_url,
        },
    )

    emitted = list(agent.stream_chat_response_with_metadata("Hej", [], "conv_ai_search_encoded_url"))

    assert emitted[-1] == {
        "type": "references",
        "references": [
            {
                "type": "url_citation",
                "title": "Discgolf%20-%20Randers%20Kommune",
                "url": decoded_public_url,
                "start_index": answer.index("\u3010"),
                "end_index": len(answer),
            }
        ],
    }


def test_stream_chat_response_with_metadata_keeps_web_search_urls_even_with_ai_search_metadata(monkeypatch):
    get_url = (
        "https://we-aisearch-it.search.windows.net/indexes/aisearch-randersdk-index/docs/doc_1"
        "?api-version=2024-07-01&$select=id,title"
    )
    web_url = "https://da.wikipedia.org/wiki/Randers"

    events = [
        SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(
                type="azure_ai_search_call_output",
                output={"get_urls": [get_url]},
            ),
        ),
        SimpleNamespace(
            type="response.output_text.annotation.added",
            annotation={
                "type": "url_citation",
                "title": "Randers Wiki",
                "url": web_url,
            },
        ),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", annotations=[])],
                    )
                ]
            ),
        ),
    ]

    class _FakeResponses:
        def __init__(self, stream_events):
            self._events = stream_events

        def create(self, **kwargs):
            return iter(self._events)

    agent = Agent.__new__(Agent)
    agent.client = SimpleNamespace(responses=_FakeResponses(events))
    agent._resolve_agent_reference = lambda use_alt: {"name": "agent_1", "type": "agent_reference"}
    agent._prepare_response_input = lambda chat_message, files: [{"role": "user", "content": []}]

    monkeypatch.setattr(
        azure_openai,
        "_fetch_ai_search_document_metadata",
        lambda get_url, timeout_s=5.0: {
            "title": "Discgolf%20-%20Randers%20Kommune",
            "url": "https://www.randers.dk/borger/fritid/discgolf",
        },
    )

    emitted = list(agent.stream_chat_response_with_metadata("Hej", [], "conv_web_search"))

    assert emitted[-1] == {
        "type": "references",
        "references": [
            {
                "type": "url_citation",
                "title": "Randers Wiki",
                "url": web_url,
            }
        ],
    }


def test_remap_ai_search_reference_urls_uses_marker_index_not_first_result(monkeypatch):
    answer = "Se den relevante side \u30105:2\u2020source\u3011"
    marker_start = answer.index("\u3010")
    references = [
        {
            "type": "url_citation",
            "title": "Ugens%20menu%20-%20Broen",
            "url": "https://we-aisearch-it.search.windows.net/doc/1",
            "start_index": marker_start,
            "end_index": len(answer),
        },
    ]
    ai_search_get_urls = [
        f"https://we-aisearch-it.search.windows.net/indexes/documents/docs/doc_{index}?api-version=2024-07-01"
        for index in range(3)
    ]
    calls = []
    metadata = [
        {"title": "Undertekstning", "url": "https://broen.randers.dk/kommunikation/undertekstning/"},
        {"title": "Webtilgaengelighed", "url": "https://broen.randers.dk/kommunikation/webtilgaengelighed/"},
        {"title": "Ugens menu - Broen", "url": "https://broen.randers.dk/ejendomsservice/kantinerne/ugens-menu/"},
    ]

    def fetch_metadata(get_url, timeout_s=5.0):
        calls.append(get_url)
        return metadata[ai_search_get_urls.index(get_url)]

    monkeypatch.setattr(azure_openai, "_fetch_ai_search_document_metadata", fetch_metadata)

    remapped = azure_openai._remap_ai_search_reference_urls(
        references=references,
        ai_search_get_urls=ai_search_get_urls,
        answer_text=answer,
    )

    assert calls == [ai_search_get_urls[2]]
    assert remapped[0]["url"] == metadata[2]["url"]


def test_remap_ai_search_reference_urls_keeps_unmatched_and_ambiguous_citations(monkeypatch):
    get_urls = [f"https://we-aisearch-it.search.windows.net/docs/{index}" for index in range(2)]
    metadata = [
        {"title": "Ugens menu - Broen", "url": "https://broen.randers.dk/menu/a/"},
        {"title": "Ugens menu - Broen", "url": "https://broen.randers.dk/menu/b/"},
    ]
    monkeypatch.setattr(
        azure_openai,
        "_fetch_ai_search_document_metadata",
        lambda get_url, timeout_s=5.0: metadata[get_urls.index(get_url)],
    )
    references = [
        {"type": "url_citation", "title": "Ugens menu - Broen", "url": "https://we-aisearch-it.search.windows.net/"},
        {"type": "url_citation", "title": "Anden side", "url": "https://we-aisearch-it.search.windows.net/"},
    ]

    calls = []
    monkeypatch.setattr(
        azure_openai,
        "_fetch_ai_search_document_metadata",
        lambda get_url, timeout_s=5.0: calls.append(get_url),
    )

    remapped = azure_openai._remap_ai_search_reference_urls(references, get_urls)

    assert [reference["url"] for reference in remapped] == ["", ""]
    assert calls == []


def test_remap_ai_search_reference_urls_does_not_guess_after_failed_lookup(monkeypatch):
    get_urls = [f"https://we-aisearch-it.search.windows.net/docs/{index}" for index in range(2)]
    answer = "Se menuen \u30105:1\u2020source\u3011"
    monkeypatch.setattr(
        azure_openai,
        "_fetch_ai_search_document_metadata",
        lambda get_url, timeout_s=5.0: (
            {"title": "Ugens menu - Broen", "url": "https://broen.randers.dk/menu/old/"}
            if get_url == get_urls[0] else None
        ),
    )
    reference = {
        "type": "url_citation",
        "title": "Ugens menu - Broen",
        "url": "https://we-aisearch-it.search.windows.net/",
        "start_index": answer.index("\u3010"),
        "end_index": len(answer),
    }

    remapped = azure_openai._remap_ai_search_reference_urls([reference], get_urls, answer_text=answer)

    assert remapped[0]["url"] == ""


def test_remap_ai_search_reference_urls_does_not_title_fallback_for_indexed_title_conflict(monkeypatch):
    get_urls = [f"https://we-aisearch-it.search.windows.net/docs/{index}" for index in range(2)]
    answer = "Læs menuen \u30105:1\u2020source\u3011"
    metadata = [
        {"title": "Menu", "url": "https://example.com/source-0"},
        {"title": "Menu revised", "url": "https://example.com/source-1"},
    ]
    calls = []

    def fetch_metadata(get_url, timeout_s=5.0):
        calls.append(get_url)
        return metadata[get_urls.index(get_url)]

    monkeypatch.setattr(azure_openai, "_fetch_ai_search_document_metadata", fetch_metadata)
    reference = {
        "type": "url_citation",
        "title": "Menu",
        "url": "https://we-aisearch-it.search.windows.net/",
        "start_index": answer.index("\u3010"),
        "end_index": len(answer),
    }

    remapped = azure_openai._remap_ai_search_reference_urls([reference], get_urls, answer_text=answer)

    assert calls == [get_urls[1]]
    assert remapped[0]["url"] == ""


def test_remap_ai_search_reference_urls_requires_nonblank_title_match(monkeypatch):
    get_url = "https://we-aisearch-it.search.windows.net/docs/0"
    answer = "Se kilden \u30105:0\u2020source\u3011"
    marker_start = answer.index("\u3010")

    for citation_title, metadata_title in (("", ""), ("Source", ""), ("", "Source")):
        monkeypatch.setattr(
            azure_openai,
            "_fetch_ai_search_document_metadata",
            lambda get_url, timeout_s=5.0, title=metadata_title: {
                "title": title,
                "url": "https://example.com/source",
            },
        )
        reference = {
            "type": "url_citation",
            "title": citation_title,
            "url": "https://we-aisearch-it.search.windows.net/",
            "start_index": marker_start,
            "end_index": len(answer),
        }

        remapped = azure_openai._remap_ai_search_reference_urls(
            [reference],
            [get_url],
            answer_text=answer,
        )

        assert remapped[0]["url"] == ""


def test_remap_ai_search_reference_urls_rejects_ambiguous_indexed_matches(monkeypatch):
    groups = [
        ["https://search.search.windows.net/docs/first"],
        ["https://search.search.windows.net/docs/second"],
    ]
    answer = "See \u30105:0\u2020source\u3011"
    reference = {
        "type": "url_citation",
        "title": "Shared title",
        "url": "https://search.search.windows.net/",
        "start_index": answer.index("\u3010"),
        "end_index": len(answer),
    }
    metadata = {
        get_url: {"title": "Shared title", "url": f"https://example.com/{group_index}"}
        for group_index, group in enumerate(groups)
        for get_url in group
    }
    monkeypatch.setattr(
        azure_openai,
        "_fetch_ai_search_document_metadata",
        lambda get_url, timeout_s=5.0: metadata[get_url],
    )

    remapped = azure_openai._remap_ai_search_reference_urls(
        [reference],
        groups[-1],
        answer_text=answer,
        ai_search_get_url_groups=groups,
    )

    assert remapped[0]["url"] == ""


def test_remap_ai_search_reference_urls_allows_time_for_multiple_result_sets(monkeypatch):
    groups = [
        [f"https://search.search.windows.net/docs/{group_index}/{index}" for index in range(5)]
        for group_index in range(8)
    ]
    answer = "See \u301026:0\u2020source\u3011"
    reference = {
        "type": "url_citation",
        "title": "Latest title",
        "url": "https://search.search.windows.net/",
        "start_index": answer.index("\u3010"),
        "end_index": len(answer),
    }
    clock = [0.0]
    calls = []

    def fetch_metadata(get_url, timeout_s=5.0):
        calls.append(get_url)
        clock[0] += 1.5
        return {
            "title": "Latest title" if get_url == groups[-1][0] else "Another title",
            "url": "https://example.com/latest",
        }

    monkeypatch.setattr(azure_openai.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(azure_openai, "_fetch_ai_search_document_metadata", fetch_metadata)

    remapped = azure_openai._remap_ai_search_reference_urls(
        [reference],
        groups[-1],
        answer_text=answer,
        ai_search_get_url_groups=groups,
    )

    assert calls == [group[0] for group in groups]
    assert clock[0] == 12.0
    assert remapped[0]["url"] == "https://example.com/latest"


def test_stream_remaps_citation_to_indexed_source_instead_of_first_result(monkeypatch):
    get_urls = [f"https://we-aisearch-it.search.windows.net/docs/{index}" for index in range(3)]
    earlier_get_urls = [f"https://we-aisearch-it.search.windows.net/docs/earlier-{index}" for index in range(3)]
    public_url = "https://broen.randers.dk/ejendomsservice/intern-service/kantinerne/ugens-menu/"
    metadata = [
        {"title": "Undertekstning", "url": "https://broen.randers.dk/kommunikation/undertekstning/"},
        {"title": "Tilgaengelighed", "url": "https://broen.randers.dk/kommunikation/tilgaengelighed/"},
        {"title": "Ugens menu - Broen", "url": public_url},
    ]
    answer = "Pa Laksetorvet: kl. 11-13\u30105:2\u2020source\u3011"
    marker_start = answer.index("\u3010")
    annotation = {
        "type": "url_citation",
        "title": "Ugens%20menu%20-%20Broen",
        "url": "https://we-aisearch-it.search.windows.net/",
        "start_index": marker_start,
        "end_index": len(answer),
    }
    earlier_search_item = SimpleNamespace(
        type="azure_ai_search_call_output",
        output={"get_urls": earlier_get_urls},
    )
    latest_search_item = SimpleNamespace(
        type="azure_ai_search_call_output",
        output={"get_urls": get_urls},
    )
    events = [
        SimpleNamespace(
            type="response.output_item.done",
            item=earlier_search_item,
        ),
        SimpleNamespace(
            type="response.output_item.done",
            item=latest_search_item,
        ),
        SimpleNamespace(type="response.output_text.delta", delta=answer),
        SimpleNamespace(type="response.output_text.annotation.added", annotation=annotation),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(output=[earlier_search_item, latest_search_item]),
        ),
    ]
    calls = []

    def fetch_metadata(get_url, timeout_s=5.0):
        calls.append(get_url)
        if get_url in earlier_get_urls:
            return {"title": "Earlier result", "url": "https://example.com/earlier"}
        return metadata[get_urls.index(get_url)]

    monkeypatch.setattr(azure_openai, "_fetch_ai_search_document_metadata", fetch_metadata)
    agent = Agent.__new__(Agent)
    agent.client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: iter(events)))
    agent._resolve_agent_reference = lambda use_alt: {"name": "agent_1", "type": "agent_reference"}
    agent._prepare_response_input = lambda chat_message, files: [{"role": "user", "content": []}]

    emitted = list(agent.stream_chat_response_with_metadata("Hej", [], "conv_menu"))

    assert calls == [earlier_get_urls[2], get_urls[2]]
    assert emitted[-1] == {
        "type": "references",
        "references": [{**annotation, "url": public_url}],
    }


def test_stream_resolves_indexed_citations_across_multiple_search_calls(monkeypatch):
    groups = [
        [f"https://search.search.windows.net/docs/{group}/{index}" for index in range(2)]
        for group in range(3)
    ]
    answer = "First \u30105:0\u2020source\u3011 second \u30108:1\u2020source\u3011 third \u301011:0\u2020source\u3011"
    titles = ["First", "Second", "Third"]
    markers = list(azure_openai._extract_ai_search_citation_markers(answer, 2))
    annotations = [
        {
            "type": "url_citation",
            "title": title,
            "url": "https://search.search.windows.net/",
            "start_index": start,
            "end_index": end,
        }
        for (start, end, _), title in zip(markers, titles)
    ]
    search_items = [
        SimpleNamespace(type="azure_ai_search_call_output", output={"get_urls": urls})
        for urls in groups
    ]
    events = [
        *(SimpleNamespace(type="response.output_item.done", item=item) for item in search_items),
        SimpleNamespace(type="response.output_text.delta", delta=answer),
        *(SimpleNamespace(type="response.output_text.annotation.added", annotation=a) for a in annotations),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                output=[
                    *search_items,
                    SimpleNamespace(type="message", content=[
                        SimpleNamespace(type="output_text", annotations=annotations),
                    ]),
                ],
            ),
        ),
    ]
    metadata = {
        url: {"title": titles[group] if index == [0, 1, 0][group] else "Other",
              "url": f"https://example.com/{group}/{index}"}
        for group, urls in enumerate(groups)
        for index, url in enumerate(urls)
    }
    monkeypatch.setattr(
        azure_openai,
        "_fetch_ai_search_document_metadata",
        lambda get_url, timeout_s=5.0: metadata[get_url],
    )
    agent = Agent.__new__(Agent)
    agent.client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: iter(events)))
    agent._resolve_agent_reference = lambda use_alt: {"name": "agent_1", "type": "agent_reference"}
    agent._prepare_response_input = lambda chat_message, files: [{"role": "user", "content": []}]

    emitted = list(agent.stream_chat_response_with_metadata("Hej", [], "conv_three_search_calls"))

    assert emitted[-1] == {
        "type": "references",
        "references": [
            {
                "type": "url_citation",
                "title": titles[group],
                "url": f"https://example.com/{group}/{index}",
                "start_index": markers[group][0],
                "end_index": markers[group][1],
            }
            for group, index in enumerate([0, 1, 0])
        ],
    }


def test_stream_does_not_resolve_citation_against_previous_nonempty_search_result(monkeypatch):
    previous_url = "https://we-aisearch-it.search.windows.net/docs/previous"
    answer = "Se kilden \u30105:0\u2020source\u3011"
    marker_start = answer.index("\u3010")
    annotation = {
        "type": "url_citation",
        "title": "Previous result",
        "url": "https://we-aisearch-it.search.windows.net/",
        "start_index": marker_start,
        "end_index": len(answer),
    }
    previous_search_item = SimpleNamespace(
        type="azure_ai_search_call_output",
        output={"get_urls": [previous_url]},
    )
    empty_search_item = SimpleNamespace(
        type="azure_ai_search_call_output",
        output={"get_urls": []},
    )
    message_item = SimpleNamespace(
        type="message",
        content=[SimpleNamespace(type="output_text", annotations=[annotation])],
    )
    events = [
        SimpleNamespace(type="response.output_item.done", item=previous_search_item),
        SimpleNamespace(type="response.output_item.done", item=empty_search_item),
        SimpleNamespace(type="response.output_text.delta", delta=answer),
        SimpleNamespace(type="response.output_text.annotation.added", annotation=annotation),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(output=[message_item]),
        ),
    ]
    metadata_calls = []

    def fetch_metadata(get_url, timeout_s=5.0):
        metadata_calls.append(get_url)
        return {"title": "Previous result", "url": "https://example.com/previous"}

    monkeypatch.setattr(azure_openai, "_fetch_ai_search_document_metadata", fetch_metadata)
    agent = Agent.__new__(Agent)
    agent.client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: iter(events)))
    agent._resolve_agent_reference = lambda use_alt: {"name": "agent_1", "type": "agent_reference"}
    agent._prepare_response_input = lambda chat_message, files: [{"role": "user", "content": []}]

    emitted = list(agent.stream_chat_response_with_metadata("Hej", [], "conv_empty_latest_search"))

    assert metadata_calls == []
    assert emitted[-1] == {"type": "references", "references": [{**annotation, "url": ""}]}


def test_stream_preserves_duplicate_ai_search_result_slots_when_remapping(monkeypatch):
    duplicate_url = "https://we-aisearch-it.search.windows.net/docs/duplicate"
    other_url = "https://we-aisearch-it.search.windows.net/docs/other"
    get_urls = [duplicate_url, duplicate_url, other_url]
    answer = "Se kilden \u30105:1\u2020source\u3011"
    marker_start = answer.index("\u3010")
    annotation = {
        "type": "url_citation",
        "title": "Shared title",
        "url": "https://we-aisearch-it.search.windows.net/",
        "start_index": marker_start,
        "end_index": len(answer),
    }
    search_item = SimpleNamespace(
        type="azure_ai_search_call_output",
        output={"get_urls": get_urls},
    )
    events = [
        SimpleNamespace(type="response.output_item.added", item=search_item),
        SimpleNamespace(type="response.output_item.done", item=search_item),
        SimpleNamespace(type="response.output_text.delta", delta=answer),
        SimpleNamespace(type="response.output_text.annotation.added", annotation=annotation),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(output=[search_item]),
        ),
    ]
    metadata_by_url = {
        duplicate_url: {
            "title": "Shared title",
            "url": "https://www.randers.dk/duplicate/",
        },
        other_url: {
            "title": "Shared title",
            "url": "https://www.randers.dk/other/",
        },
    }
    calls = []

    def fetch_metadata(get_url, timeout_s=5.0):
        calls.append(get_url)
        return metadata_by_url[get_url]

    monkeypatch.setattr(azure_openai, "_fetch_ai_search_document_metadata", fetch_metadata)
    agent = Agent.__new__(Agent)
    agent.client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: iter(events)))
    agent._resolve_agent_reference = lambda use_alt: {"name": "agent_1", "type": "agent_reference"}
    agent._prepare_response_input = lambda chat_message, files: [{"role": "user", "content": []}]

    emitted = list(agent.stream_chat_response_with_metadata("Hej", [], "conv_duplicate_search_results"))

    assert calls == [duplicate_url]
    assert emitted[-1]["references"][0]["url"] == metadata_by_url[duplicate_url]["url"]


def test_remap_ai_search_reference_urls_uses_citation_marker_for_duplicate_titles(monkeypatch):
    get_urls = [f"https://we-aisearch-it.search.windows.net/docs/{index}" for index in range(3)]
    metadata = [
        {"title": "Ugens menu - Broen", "url": "https://broen.randers.dk/menu/old/"},
        {"title": "Anden side", "url": "https://broen.randers.dk/anden-side/"},
        {"title": "Ugens menu - Broen", "url": "https://broen.randers.dk/menu/current/"},
    ]
    calls = []

    def fetch_metadata(get_url, timeout_s=5.0):
        calls.append(get_url)
        return metadata[get_urls.index(get_url)]

    monkeypatch.setattr(azure_openai, "_fetch_ai_search_document_metadata", fetch_metadata)
    answer = "\U0001f600 Pa Laksetorvet: kl. 11-13\u30105:2\u2020source\u3011 bagefter"
    marker_start = answer.index("\u3010")
    references = [{
        "type": "url_citation",
        "title": "Ugens%20menu%20-%20Broen",
        "url": "https://we-aisearch-it.search.windows.net/",
        "start_index": azure_openai._python_index_to_utf16(answer, marker_start),
        "end_index": azure_openai._python_index_to_utf16(answer, len(answer)),
    }]

    remapped = azure_openai._remap_ai_search_reference_urls(references, get_urls, answer_text=answer)

    assert calls == [get_urls[2]]
    assert remapped[0]["url"] == metadata[2]["url"]


def test_stream_reconstructs_ai_search_reference_when_annotations_are_missing(monkeypatch):
    get_urls = [
        "https://we-aisearch-it.search.windows.net/indexes/documents/docs/doc_0?api-version=2024-07-01",
        "https://we-aisearch-it.search.windows.net/indexes/documents/docs/doc_1?api-version=2024-07-01",
    ]
    public_url = "https://www.randers.dk/borger/fritid/discgolf/"
    metadata_title = "Discgolf%20-%20Randers%20Kommune"
    answer = "Se reglerne her cite8:1†source."
    events = [
        SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(
                type="azure_ai_search_call_output",
                output={"get_urls": get_urls},
            ),
        ),
        SimpleNamespace(type="response.output_text.delta", delta="Se reglerne her cite"),
        SimpleNamespace(type="response.output_text.delta", delta="8:1†source."),
        SimpleNamespace(
            type="response.content_part.done",
            part=SimpleNamespace(type="output_text", annotations=[]),
        ),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", annotations=[])],
                    )
                ]
            ),
        ),
    ]

    class _FakeResponses:
        def create(self, **kwargs):
            return iter(events)

    requested_get_urls = []

    def fetch_metadata(get_url, timeout_s=5.0):
        requested_get_urls.append(get_url)
        return {
            "title": metadata_title,
            "url": "https%3A%2F%2Fwww.randers.dk%2Fborger%2Ffritid%2Fdiscgolf%2F",
        }

    monkeypatch.setattr(azure_openai, "_fetch_ai_search_document_metadata", fetch_metadata)

    agent = Agent.__new__(Agent)
    agent.client = SimpleNamespace(responses=_FakeResponses())
    agent._resolve_agent_reference = lambda use_alt: {"name": "agent_1", "type": "agent_reference"}
    agent._prepare_response_input = lambda chat_message, files: [{"role": "user", "content": []}]

    emitted = list(agent.stream_chat_response_with_metadata("Hej", [], "conv_missing_annotations"))

    marker_start = answer.index("cite")
    marker_end = answer.index("") + 1
    assert requested_get_urls == [get_urls[1]]
    assert emitted[-1] == {
        "type": "references",
        "references": [
            {
                "type": "url_citation",
                "start_index": marker_start,
                "end_index": marker_end,
                "title": metadata_title,
                "url": public_url,
            }
        ],
    }


def test_stream_does_not_apply_ai_search_marker_fallback_when_web_search_is_present(monkeypatch):
    get_url = "https://we-aisearch-it.search.windows.net/indexes/documents/docs/doc_0?api-version=2024-07-01"
    events = [
        SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(
                type="azure_ai_search_call_output",
                output={"get_urls": [get_url]},
            ),
        ),
        SimpleNamespace(
            type="response.output_item.added",
            item=SimpleNamespace(type="web_search_call"),
        ),
        SimpleNamespace(type="response.output_text.delta", delta="Svar cite8:0†source"),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                output=[
                    SimpleNamespace(type="web_search_call"),
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="output_text", annotations=[])],
                    ),
                ]
            ),
        ),
    ]

    class _FakeResponses:
        def create(self, **kwargs):
            return iter(events)

    monkeypatch.setattr(
        azure_openai,
        "_fetch_ai_search_document_metadata",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("AI Search fallback must not run")),
    )

    agent = Agent.__new__(Agent)
    agent.client = SimpleNamespace(responses=_FakeResponses())
    agent._resolve_agent_reference = lambda use_alt: {"name": "agent_1", "type": "agent_reference"}
    agent._prepare_response_input = lambda chat_message, files: [{"role": "user", "content": []}]

    emitted = list(agent.stream_chat_response_with_metadata("Hej", [], "conv_mixed_search"))

    assert emitted[-1] == {"type": "references", "references": []}


def test_build_ai_search_references_from_text_supports_bracket_marker_without_turn_index(monkeypatch):
    get_urls = [
        "https://we-aisearch-it.search.windows.net/indexes/documents/docs/doc_0?api-version=2024-07-01",
    ]
    answer = "Se kilden her 【0†source】."

    monkeypatch.setattr(
        azure_openai,
        "_fetch_ai_search_document_metadata",
        lambda get_url, timeout_s=5.0: {
            "title": "Regler",
            "url": "https://www.randers.dk/regler",
        },
    )

    references = azure_openai._build_ai_search_references_from_text(answer, get_urls)

    assert references == [
        {
            "type": "url_citation",
            "start_index": answer.index("【"),
            "end_index": answer.index("】") + 1,
            "title": "Regler",
            "url": "https://www.randers.dk/regler",
        }
    ]


def test_extract_ai_search_citation_markers_supports_malformed_foundry_variants():
    cases = [
        ("Svar turn7search3", [3]),
        ("Svar 15:015:1", [0, 1]),
        ("Svar turn7:3turn7:4", [3, 4]),
    ]

    for answer, expected_indices in cases:
        markers = azure_openai._extract_ai_search_citation_markers(answer, source_count=5)

        assert len(markers) == 1
        assert markers[0][2] == expected_indices


def test_extract_ai_search_citation_markers_only_infers_indexless_marker_for_one_source():
    answers = [
        "Svar. cite? no, must use Azure citation format.",
        "Svar. turn7source",
    ]

    for answer in answers:
        marker_start = answer.index("cite") if "cite" in answer else answer.index("turn7")
        assert azure_openai._extract_ai_search_citation_markers(answer, source_count=5) == []
        assert azure_openai._extract_ai_search_citation_markers(answer, source_count=1) == [
            (marker_start, len(answer), [0])
        ]
