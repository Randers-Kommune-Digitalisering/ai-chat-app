from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


class _DummyThread:
    def __init__(self):
        self.join_called = 0

    def join(self, timeout=None):
        self.join_called += 1


class _HungThread:
    def __init__(self):
        self.join_called = 0
        self.last_timeout = None

    def join(self, timeout=None):
        self.join_called += 1
        self.last_timeout = timeout

    def is_alive(self):
        return True


@pytest.fixture()
def app():
    from main import create_app

    app = create_app()
    app.config.update({
        "TESTING": True,
    })
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def _post_thread_message(
    client,
    *,
    thread_id: str,
    message: str,
    files=None,
    use_alt: bool = False,
    conversation_id=None,
    user_email: str = "user@example.com",
):
    payload = {
        "message": message,
        "files": files or [],
        "use_alt": use_alt,
    }
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id

    return client.post(
        f"/api/threads/{thread_id}/messages",
        json=payload,
        headers={"X-User-Email": user_email} if user_email else {},
    )


def test_thread_message_stream_forwards_status_separately_from_text(client):
    stream_events = iter([
        {"type": "status", "status": "thinking", "message": "Assistenten tænker ..."},
        {"type": "delta", "text": "Et svar"},
        {"type": "references", "references": []},
    ])

    with patch("api_endpoints.USE_DB", False), patch(
        "api_endpoints.redact_content",
        side_effect=lambda *, text: text,
    ), patch(
        "api_endpoints.azure_client",
        SimpleNamespace(stream_chat_response_with_metadata=lambda **kwargs: stream_events),
    ):
        response = client.post(
            "/api/threads/conv_status/messages/stream",
            json={"message": "Hej", "files": [], "use_alt": False},
        )
        body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "event: status\ndata: {\"status\": \"thinking\", \"message\": \"Assistenten tænker ...\"}" in body
    assert "event: delta\ndata: {\"text\": \"Et svar\"}" in body
    assert body.index("event: status") < body.index("event: delta") < body.index("event: end")


def test_thread_message_stream_rejects_token_overflow_before_stream(client):
    with patch(
        "api_endpoints.redact_content",
        side_effect=lambda *, text: text,
    ), patch(
        "api_endpoints.count_tokens",
        return_value=10**9,
    ):
        response = client.post(
            "/api/threads/conv_overflow/messages/stream",
            json={
                "message": "Hej",
                "files": [{"name": "doc.txt", "content": "SGVq"}],
                "use_alt": False,
            },
        )

    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert "for lang" in body["message"]


def test_thread_message_rejects_file_over_size_limit_before_azure(client):
    with patch("api_endpoints.AGENT_FILE_SIZE_LIMIT", 2), patch(
        "api_endpoints.redact_content",
        side_effect=lambda *, text: text,
    ), patch(
        "api_endpoints.azure_client.fetch_chat_response",
    ) as mock_fetch:
        response = _post_thread_message(
            client,
            thread_id="conv_file_limit",
            message="Hej",
            files=[{"name": "doc.txt", "content": "SGVq"}],
        )

    assert response.status_code == 413
    assert response.get_json()["success"] is False
    mock_fetch.assert_not_called()


def test_thread_message_stream_rejects_file_over_size_limit_before_azure(client):
    with patch("api_endpoints.AGENT_FILE_SIZE_LIMIT", 2), patch(
        "api_endpoints.redact_content",
        side_effect=lambda *, text: text,
    ), patch(
        "api_endpoints.azure_client.stream_chat_response_with_metadata",
    ) as mock_stream:
        response = client.post(
            "/api/threads/conv_stream_file_limit/messages/stream",
            json={
                "message": "Hej",
                "files": [{"name": "doc.txt", "content": "SGVq"}],
                "use_alt": False,
            },
        )

    assert response.status_code == 413
    assert response.get_json()["success"] is False
    mock_stream.assert_not_called()


def test_thread_messages_db_unavailable_still_returns_success(client):
    dummy_thread = _DummyThread()
    title_result = {"title": "Generated title"}

    with patch(
        "api_endpoints.redact_content",
        side_effect=lambda *, text: text,
    ), patch(
        "api_endpoints._start_title_generation_thread",
        return_value=(dummy_thread, title_result),
    ) as mock_start_title, patch(
        "api_endpoints.azure_client.fetch_chat_response",
        return_value=("assistant reply", [{"url": "https://example.com"}], None),
    ), patch(
        "api_endpoints.db_client.get_session",
        side_effect=Exception("db down"),
    ):
        res = _post_thread_message(client, thread_id="thr_1", message="Hi")

    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    assert body["response"] == "assistant reply"
    assert body["references"] == [{"url": "https://example.com"}]

    assert body.get("conversation_id") is None
    assert body.get("title") is None

    # Title generation starts only after DB session is confirmed.
    assert dummy_thread.join_called == 0
    mock_start_title.assert_not_called()


def test_thread_messages_creates_conversation_persists_messages_and_returns_title_and_id(client):
    dummy_thread = _DummyThread()
    title_result = {"title": "Generated title"}

    db_session = MagicMock()
    created_conversation = MagicMock()
    created_conversation.id = 456

    with patch(
        "api_endpoints.redact_content",
        side_effect=lambda *, text: text,
    ), patch(
        "api_endpoints._start_title_generation_thread",
        return_value=(dummy_thread, title_result),
    ), patch(
        "api_endpoints.azure_client.fetch_chat_response",
        return_value=("assistant reply", [], None),
    ), patch(
        "api_endpoints.db_client.get_session",
        return_value=db_session,
    ), patch(
        "api_endpoints.chat_conversations_counter",
    ) as mock_conv_counter, patch(
        "api_endpoints.create_db_conversation",
        return_value=created_conversation,
    ) as mock_create_conv, patch(
        "api_endpoints.add_message_to_conversation",
        side_effect=[True, True],
    ) as mock_add_msg:
        res = _post_thread_message(client, thread_id="thr_2", message="Hi")

    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    assert body["response"] == "assistant reply"
    assert body.get("conversation_id") == 456
    assert body.get("title") == "Generated title"

    assert dummy_thread.join_called == 1

    mock_create_conv.assert_called_once()
    _, kwargs = mock_create_conv.call_args
    assert kwargs.get("thread_id") == "thr_2"

    assert mock_add_msg.call_count == 2

    mock_conv_counter.labels.assert_called_once()
    assert mock_conv_counter.labels.call_args.kwargs.get("mode") == "agent"
    mock_conv_counter.labels.return_value.inc.assert_called_once()
    db_session.close.assert_called_once()


def test_thread_messages_persists_only_file_metadata_when_enabled(client):
    db_session = MagicMock()

    with patch(
        "api_endpoints.AGENT_FILE_METADATA_ONLY",
        True,
    ), patch(
        "api_endpoints.redact_content",
        side_effect=lambda *, text: text,
    ), patch(
        "api_endpoints.azure_client.fetch_chat_response",
        return_value=("assistant reply", [], None),
    ), patch(
        "api_endpoints.db_client.get_session",
        return_value=db_session,
    ), patch(
        "api_endpoints.add_message_to_conversation",
        side_effect=[True, True],
    ) as mock_add_msg:
        res = _post_thread_message(
            client,
            thread_id="thr_metadata",
            message="Hi",
            files=[{"name": "doc.txt", "content": "SGVq"}],
            conversation_id=123,
        )

    assert res.status_code == 200
    assert mock_add_msg.call_args_list[0].kwargs["file_content"] == [{
        "file_name": "doc.txt",
        "file_type": "text/plain",
        "file_size": 3,
    }]


def test_thread_messages_persists_file_content_when_metadata_only_disabled(client):
    db_session = MagicMock()

    with patch(
        "api_endpoints.AGENT_FILE_METADATA_ONLY",
        False,
    ), patch(
        "api_endpoints.redact_content",
        side_effect=lambda *, text: text,
    ), patch(
        "api_endpoints.azure_client.fetch_chat_response",
        return_value=("assistant reply", [], None),
    ), patch(
        "api_endpoints.db_client.get_session",
        return_value=db_session,
    ), patch(
        "api_endpoints.add_message_to_conversation",
        side_effect=[True, True],
    ) as mock_add_msg:
        res = _post_thread_message(
            client,
            thread_id="thr_content",
            message="Hi",
            files=[{"name": "doc.txt", "content": "SGVq"}],
            conversation_id=123,
        )

    assert res.status_code == 200
    stored_file = mock_add_msg.call_args_list[0].kwargs["file_content"][0]
    assert stored_file.filename == "doc.txt"
    assert stored_file.getvalue() == b"Hej"


def test_thread_messages_create_conversation_fails_still_returns_success_with_title(client):
    dummy_thread = _DummyThread()
    title_result = {"title": "Generated title"}

    db_session = MagicMock()

    with patch(
        "api_endpoints.redact_content",
        side_effect=lambda *, text: text,
    ), patch(
        "api_endpoints._start_title_generation_thread",
        return_value=(dummy_thread, title_result),
    ), patch(
        "api_endpoints.azure_client.fetch_chat_response",
        return_value=("assistant reply", [], None),
    ), patch(
        "api_endpoints.db_client.get_session",
        return_value=db_session,
    ), patch(
        "api_endpoints.chat_conversations_counter",
    ) as mock_conv_counter, patch(
        "api_endpoints.create_db_conversation",
        return_value=None,
    ), patch(
        "api_endpoints.add_message_to_conversation",
    ) as mock_add_msg:
        res = _post_thread_message(client, thread_id="thr_3", message="Hi")

    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    assert body["response"] == "assistant reply"

    assert body.get("conversation_id") is None
    assert body.get("title") == "Generated title"

    assert dummy_thread.join_called == 1
    mock_add_msg.assert_not_called()
    mock_conv_counter.labels.assert_not_called()
    db_session.close.assert_called_once()


def test_thread_messages_partial_write_user_message_insert_fails_still_returns_success(client):
    dummy_thread = _DummyThread()
    title_result = {"title": "Generated title"}

    db_session = MagicMock()
    created_conversation = MagicMock()
    created_conversation.id = 456

    with patch(
        "api_endpoints.redact_content",
        side_effect=lambda *, text: text,
    ), patch(
        "api_endpoints._start_title_generation_thread",
        return_value=(dummy_thread, title_result),
    ), patch(
        "api_endpoints.azure_client.fetch_chat_response",
        return_value=("assistant reply", [], None),
    ), patch(
        "api_endpoints.db_client.get_session",
        return_value=db_session,
    ), patch(
        "api_endpoints.chat_conversations_counter",
    ) as mock_conv_counter, patch(
        "api_endpoints.create_db_conversation",
        return_value=created_conversation,
    ), patch(
        "api_endpoints.add_message_to_conversation",
        side_effect=[False],
    ) as mock_add_msg:
        res = _post_thread_message(client, thread_id="thr_4", message="Hi")

    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    assert body["response"] == "assistant reply"

    assert body.get("conversation_id") == 456
    assert body.get("title") == "Generated title"

    assert dummy_thread.join_called == 1
    assert mock_add_msg.call_count == 1

    mock_conv_counter.labels.assert_called_once()
    assert mock_conv_counter.labels.call_args.kwargs.get("mode") == "agent"
    mock_conv_counter.labels.return_value.inc.assert_called_once()
    db_session.close.assert_called_once()


def test_thread_messages_propagates_rate_limit_status_from_azure_wrapper(client):
    with patch(
        "api_endpoints.redact_content",
        side_effect=lambda *, text: text,
    ), patch(
        "api_endpoints.azure_client.fetch_chat_response",
        return_value=(None, [], "Assistenten er travl lige nu. Prøv igen senere.", 429),
    ):
        res = _post_thread_message(client, thread_id="thr_rate", message="Hi")

    assert res.status_code == 429
    body = res.get_json()
    assert body["success"] is False
    assert "travl" in body["message"].lower()


def test_thread_messages_title_join_timeout_uses_fallback_and_tracks_metric(client):
    import api_endpoints

    hung_thread = _HungThread()
    title_result = {"title": "Generated title"}

    db_session = MagicMock()
    created_conversation = MagicMock()
    created_conversation.id = 654

    with patch(
        "api_endpoints.redact_content",
        side_effect=lambda *, text: text,
    ), patch(
        "api_endpoints._start_title_generation_thread",
        return_value=(hung_thread, title_result),
    ), patch(
        "api_endpoints.azure_client.fetch_chat_response",
        return_value=("assistant reply", [], None),
    ), patch(
        "api_endpoints.db_client.get_session",
        return_value=db_session,
    ), patch(
        "api_endpoints.chat_conversations_counter",
    ), patch(
        "api_endpoints.title_generation_timeout_counter",
    ) as mock_timeout_counter, patch(
        "api_endpoints.create_db_conversation",
        return_value=created_conversation,
    ) as mock_create_conv, patch(
        "api_endpoints.add_message_to_conversation",
        side_effect=[True, True],
    ):
        res = _post_thread_message(client, thread_id="thr_timeout", message="Hi")

    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    assert body.get("conversation_id") == 654
    assert body.get("title") == "Samtale thr_timeout"

    assert hung_thread.join_called == 1
    assert hung_thread.last_timeout == api_endpoints.TITLE_GENERATION_JOIN_TIMEOUT_S

    mock_timeout_counter.labels.assert_called_once()
    assert mock_timeout_counter.labels.call_args.kwargs.get("mode") == "agent"
    mock_timeout_counter.labels.return_value.inc.assert_called_once()

    assert mock_create_conv.call_args.kwargs.get("title") == "Samtale thr_timeout"
