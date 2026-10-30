from unittest.mock import patch

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


def test_frontend_config_response_fields(client):
    response = client.get('/api/config')

    assert response.status_code == 200
    assert set(response.get_json()) == {
        'assistantName', 'assistantNameId', 'assistantType', 'isAgent',
        'predefinedQuestions', 'description', 'showAssistantToggle',
        'altToggleLabel', 'altAlertMsg', 'altAlertType',
        'agentFileSizeLimit', 'conversationLoadCutoffDate',
    }


def test_filter_response_contract(client):
    with patch('api_endpoints.get_filter_content', return_value=['123456-7890']) as mock_filter:
        response = client.post('/api/filter', json={'content': 'example text'})

    assert response.status_code == 200
    assert response.get_json() == {'success': True, 'filtered_content': ['123456-7890']}
    mock_filter.assert_called_once_with('example text')

    invalid_response = client.post('/api/filter', json={'content': ''})
    assert invalid_response.status_code == 400
    assert invalid_response.get_json()['success'] is False


def test_feedback_response_contract(client):
    payload = {'feedback': 'Helpful', 'response_index': 0, 'chat_history': []}
    with patch('api_endpoints.send_user_feedback', return_value={'sent': True}) as mock_send:
        response = client.post('/api/feedback', json=payload)

    assert response.status_code == 200
    assert response.get_json() == {'success': True, 'data': {'sent': True}}
    mock_send.assert_called_once_with('Helpful', 0, [])

    invalid_response = client.post('/api/feedback', json={'feedback': 'Helpful'})
    assert invalid_response.status_code == 400
    assert invalid_response.get_json()['success'] is False
