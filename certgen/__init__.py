"""Bulk Certificate Generator application factory."""
from __future__ import annotations

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from .certificate import render_certificate
from .config import default_config
from .db import init_db
from .jobs import JobService
from .routes import api


def create_app(overrides: dict | None = None, renderer=None) -> Flask:
    """Build the Flask app.

    ``overrides`` replaces configuration values (used by tests).
    ``renderer`` replaces the PDF renderer (used by tests to simulate failures).
    """
    app = Flask(__name__)
    app.config.update(default_config())
    if overrides:
        app.config.update(overrides)

    init_db(app.config["DATABASE_PATH"])
    os.makedirs(app.config["STORAGE_DIR"], exist_ok=True)

    app.extensions["job_service"] = JobService(
        db_path=app.config["DATABASE_PATH"],
        storage_dir=app.config["STORAGE_DIR"],
        renderer=renderer or render_certificate,
        synchronous=app.config["PROCESS_SYNCHRONOUSLY"],
        workers=app.config["WORKER_THREADS"],
    )

    app.register_blueprint(api)

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        # Return JSON instead of HTML for errors such as 404 or 413.
        return jsonify(error=exc.description), exc.code

    return app
