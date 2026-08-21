from types import SimpleNamespace

from utils.azure_openai2 import Agent, _extract_native_annotations_from_stream_event


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

    assert emitted[0] == {"type": "delta", "text": "Svar "}
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

    assert emitted[0] == {"type": "delta", "text": "Svar "}
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
