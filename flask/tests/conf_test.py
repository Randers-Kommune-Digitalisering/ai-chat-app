import pytest


@pytest.fixture()
def app():
    # Import inside fixture so pytest-env has applied `pytest.ini` env vars first.
    from main import create_app

    app = create_app()
    app.config.update({
        "TESTING": True,
    })
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def test_healthz(client):
    response = client.get('/healthz')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'success'


def test_metrics(client):
    # POD_NAME env var set in pytest.ini (test-pod)
    response = client.get('/metrics')
    assert response.status_code == 200
    assert 'is_ready gauge\nis_ready{error_type="None",job_name="test-pod"} 1.0' in response.text


def test_like_feedback_endpoint_exposes_metric(client):
    response = client.post('/api/feedback/like', json={"response_index": "msg_0"})
    assert response.status_code == 200
    assert response.get_json()["success"] is True

    metrics_response = client.get('/metrics')
    assert metrics_response.status_code == 200
    assert 'chat_feedback_total' in metrics_response.text
    assert 'feedback_type="like"' in metrics_response.text
