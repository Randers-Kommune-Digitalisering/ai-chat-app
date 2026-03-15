import os
from flask import Flask, Response, send_from_directory
from healthcheck import HealthCheck
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from utils.logging import set_logging_configuration, is_ready_gauge, last_updated_gauge
from utils.config import DEBUG, PORT, POD_NAME
import utils.config as config
from api_endpoints import api_endpoints

set_logging_configuration()


def create_app():
    app = Flask(__name__, static_folder='dist', static_url_path='/')
    health = HealthCheck()
    app.add_url_rule('/healthz', 'healthcheck', view_func=lambda: health.run())

    def metrics():
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    app.add_url_rule('/metrics', 'metrics', view_func=metrics)

    app.register_blueprint(api_endpoints)

    @app.after_request
    def add_security_headers(response):
        # Prevent embedding by untrusted sites.
        # Configure via CSP_FRAME_ANCESTORS, e.g.:
        #   "'self' https://chat.data.randers.dk https://ai.data.randers.dk"
        # or a full directive string containing "frame-ancestors".
        try:
            value = (config.CSP_FRAME_ANCESTORS or '').strip()
            if value:
                directive = value if 'frame-ancestors' in value else f"frame-ancestors {value}"
                response.headers['Content-Security-Policy'] = directive
        except Exception:
            pass
        return response

    @app.before_request
    def set_ready():
        is_ready_gauge.labels(job_name=POD_NAME, error_type=None).set(1)
        last_updated_gauge.set_to_current_time()

    return app


app = create_app()


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(app.static_folder + '/' + path):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')


if __name__ == '__main__':  # pragma: no cover
    app.run(debug=DEBUG, host='0.0.0.0', port=PORT)
