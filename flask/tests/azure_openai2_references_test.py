from types import SimpleNamespace

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
