import pytest

from certgen import create_app
from certgen.certificate import render_certificate

# A recipient with this name makes the renderer raise, simulating a real failure.
SIMULATED_FAILURE_NAME = "Simulated Failure"


def flaky_renderer(output_path, *, recipient_name, **kwargs):
    if recipient_name == SIMULATED_FAILURE_NAME:
        raise RuntimeError("simulated renderer failure")
    return render_certificate(output_path, recipient_name=recipient_name, **kwargs)


def _config(tmp_path, synchronous: bool) -> dict:
    return {
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "test.db"),
        "STORAGE_DIR": str(tmp_path / "certificates"),
        "PROCESS_SYNCHRONOUSLY": synchronous,
    }


@pytest.fixture
def app(tmp_path):
    """App that renders inline, so results are ready when the response returns."""
    return create_app(_config(tmp_path, synchronous=True), renderer=flaky_renderer)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def threaded_app(tmp_path):
    """App that uses the real background thread pool."""
    return create_app(_config(tmp_path, synchronous=False), renderer=flaky_renderer)


@pytest.fixture
def valid_recipients():
    return [
        {"name": "Asha Patel", "email": "asha@example.com"},
        {"name": "Ravi Shah", "email": "ravi@example.com"},
    ]
