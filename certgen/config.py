"""Application configuration, read from environment variables with sensible defaults."""
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def default_config() -> dict:
    storage_root = os.environ.get("CERT_STORAGE_DIR", os.path.join(BASE_DIR, "storage"))
    return {
        # SQLite database file (created automatically on first run).
        "DATABASE_PATH": os.environ.get("CERT_DB_PATH", os.path.join(storage_root, "app.db")),
        # Folder where generated PDFs are written.
        "STORAGE_DIR": os.environ.get("CERT_CERT_DIR", os.path.join(storage_root, "certificates")),
        # Maximum recipients accepted in one job request.
        "MAX_RECIPIENTS": int(os.environ.get("CERT_MAX_RECIPIENTS", "5000")),
        # Number of background threads that render certificates.
        "WORKER_THREADS": int(os.environ.get("CERT_WORKER_THREADS", "4")),
        # When True, certificates are rendered inside the request (used by tests).
        "PROCESS_SYNCHRONOUSLY": False,
        # Reject request bodies larger than 5 MB.
        "MAX_CONTENT_LENGTH": 5 * 1024 * 1024,
    }
