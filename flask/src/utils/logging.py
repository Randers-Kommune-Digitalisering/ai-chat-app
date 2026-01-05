import sys
import logging
import re

from werkzeug import serving
from prometheus_client import Gauge, Counter

from utils.config import DEBUG, METRICS_APP, METRICS_DEPLOYMENT, METRICS_INSTANCE

# Prometheus metricts

# Availavility metrics
is_ready_gauge = Gauge('is_ready', '1 - app is running, 0 - app is down', labelnames=['error_type', 'job_name'])
last_updated_gauge = Gauge('last_updated_ms', "Timestamp in milliseconds of the last time the app's availability was updated")

# Dependency metrics
is_available_gauge = Gauge('is_available', '1 - dependency is available, 0 - dependency is not available', labelnames=['dependency_name'])


def metrics_base_labels() -> dict:
    return {
        'app': METRICS_APP,
        'deployment': METRICS_DEPLOYMENT,
        'instance': METRICS_INSTANCE,
    }


# App metrics
chat_messages_counter = Counter(
    'chat_messages_total',
    'Number of user messages received by the backend',
    labelnames=['app', 'deployment', 'instance', 'mode'],
)

chat_feedback_counter = Counter(
    'chat_feedback_total',
    'Number of feedback events received by the backend',
    labelnames=['app', 'deployment', 'instance', 'feedback_type'],
)


# Logging configuration
def set_logging_configuration():
    log_level = logging.DEBUG if DEBUG else logging.INFO
    logging.basicConfig(stream=sys.stdout, level=log_level, format='[%(asctime)s] %(levelname)s - %(name)s - %(module)s:%(funcName)s - %(message)s', datefmt='%d-%m-%Y %H:%M:%S')
    disable_endpoint_logs(('/metrics', '/healthz'))


def disable_endpoint_logs(disabled_endpoints):
    parent_log_request = serving.WSGIRequestHandler.log_request

    def log_request(self, *args, **kwargs):
        if not any(re.match(f"{de}$", self.path) for de in disabled_endpoints):
            parent_log_request(self, *args, **kwargs)

    serving.WSGIRequestHandler.log_request = log_request
