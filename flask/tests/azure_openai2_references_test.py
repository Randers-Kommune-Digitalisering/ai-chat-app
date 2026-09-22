from types import SimpleNamespace

import utils.azure_openai2 as azure_openai2
from utils.azure_openai2 import Agent, _extract_native_annotations_from_stream_event, _status_for_stream_event


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

    assert azure_openai2._extract_ai_search_get_urls_from_stream_event(event=event) == [get_url]


def test_normalize_ai_search_get_url_sets_select_to_title_and_url():
    input_url = (
        "https://we-aisearch-it.search.windows.net/indexes/aisearch-randersdk-index/docs/doc_1"
        "?api-version=2024-07-01&$select=id,content,title"
    )

    normalized = azure_openai2._normalize_ai_search_get_url(input_url)
    parsed = azure_openai2.urllib.parse.urlparse(normalized)
    query = azure_openai2.urllib.parse.parse_qs(parsed.query)

    assert query["$select"] == ["title,url"]
    assert query["api-version"] == ["2024-07-01"]


def test_stream_chat_response_with_metadata_remaps_internal_ai_search_urls(monkeypatch):
    get_url = (
        "https://we-aisearch-it.search.windows.net/indexes/aisearch-randersdk-index/docs/doc_1"
        "?api-version=2024-07-01&$select=id,title"
    )
    public_url = "https://www.randers.dk/borger/fritid/discgolf"

    events = [
        SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(
                type="azure_ai_search_call_output",
                output={"get_urls": [get_url]},
            ),
        ),
        SimpleNamespace(type="response.output_text.delta", delta="Svar "),
        SimpleNamespace(
            type="response.output_text.annotation.added",
            annotation={
                "type": "url_citation",
                "title": "Discgolf%20-%20Randers%20Kommune",
                "url": "https://we-aisearch-it.search.windows.net/",
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
        azure_openai2,
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
                "title": "Discgolf%20-%20Randers%20Kommune",
                "url": "https://we-aisearch-it.search.windows.net/",
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
        azure_openai2,
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
        azure_openai2,
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

    monkeypatch.setattr(azure_openai2, "_fetch_ai_search_document_metadata", fetch_metadata)

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
        azure_openai2,
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
        azure_openai2,
        "_fetch_ai_search_document_metadata",
        lambda get_url, timeout_s=5.0: {
            "title": "Regler",
            "url": "https://www.randers.dk/regler",
        },
    )

    references = azure_openai2._build_ai_search_references_from_text(answer, get_urls)

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
        markers = azure_openai2._extract_ai_search_citation_markers(answer, source_count=5)

        assert len(markers) == 1
        assert markers[0][2] == expected_indices


def test_extract_ai_search_citation_markers_only_infers_indexless_marker_for_one_source():
    answers = [
        "Svar. cite? no, must use Azure citation format.",
        "Svar. turn7source",
    ]

    for answer in answers:
        marker_start = answer.index("cite") if "cite" in answer else answer.index("turn7")
        assert azure_openai2._extract_ai_search_citation_markers(answer, source_count=5) == []
        assert azure_openai2._extract_ai_search_citation_markers(answer, source_count=1) == [
            (marker_start, len(answer), [0])
        ]
