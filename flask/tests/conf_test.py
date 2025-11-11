import pytest
import os
from main import create_app

# Set all required environment variables to dummy values for tests
os.environ['AZURE_OPENAI_KEY'] = 'dummy-key'
os.environ['AZURE_OPENAI_ENDPOINT'] = 'dummy-endpoint'
os.environ['AZURE_OPENAI_DEPLOYMENT_NAME'] = 'dummy-deployment'
os.environ['ASSISTANT_ID'] = 'dummy-assistant-id'
os.environ['FEEDBACK_MAIL_API_URL'] = 'dummy-feedback-url'
os.environ['FEEDBACK_MAIL_API_RECIPIENT'] = 'dummy-recipient@example.com'
os.environ['FEEDBACK_MAIL_API_SENDER'] = 'dummy-sender@example.com'


@pytest.fixture()
def app():
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
