"""HTTP endpoints. Routes only translate HTTP <-> service calls; logic lives in jobs.py and validation.py."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request, send_file

from .jobs import ITEM_STATUSES, JOB_PROCESSING
from .validation import RequestError, parse_job_request

api = Blueprint("api", __name__, url_prefix="/api")


def _service():
    return current_app.extensions["job_service"]


def _error(message: str, status: int, details=None):
    body = {"error": message}
    if details:
        body["details"] = details
    return jsonify(body), status


@api.post("/jobs")
def create_job():
    """Submit a bulk certificate job. Returns 202 Accepted with a status URL."""
    payload = request.get_json(silent=True)
    if payload is None:
        return _error("Request body must be valid JSON (Content-Type: application/json).", 400)

    try:
        job_request = parse_job_request(payload, max_recipients=current_app.config["MAX_RECIPIENTS"])
    except RequestError as exc:
        return _error(exc.message, exc.status, exc.details)

    job = _service().create_job(job_request)
    job_url = f"/api/jobs/{job['job_id']}"
    body = {
        "job": job,
        "accepted": len(job_request.accepted),
        "rejected": [r.to_dict() for r in job_request.rejected],
        "links": {
            "self": job_url,
            "items": f"{job_url}/items",
            "certificates_zip": f"{job_url}/certificates.zip",
        },
    }
    return jsonify(body), 202, {"Location": job_url}


@api.get("/jobs/<job_id>")
def get_job(job_id: str):
    job = _service().get_job(job_id)
    if job is None:
        return _error("Job not found.", 404)
    return jsonify(job)


@api.get("/jobs/<job_id>/items")
def list_items(job_id: str):
    """Per-recipient results. Filter with ?status=SUCCEEDED or ?status=FAILED."""
    service = _service()
    if service.get_job(job_id) is None:
        return _error("Job not found.", 404)

    status = request.args.get("status")
    if status is not None:
        status = status.upper()
        if status not in ITEM_STATUSES:
            return _error(f"'status' must be one of: {', '.join(ITEM_STATUSES)}.", 400)

    items = service.list_items(job_id, status)
    return jsonify({"job_id": job_id, "count": len(items), "items": items})


@api.get("/jobs/<job_id>/items/<int:item_id>/certificate")
def download_certificate(job_id: str, item_id: int):
    path = _service().get_certificate_path(job_id, item_id)
    if path is None:
        return _error("No generated certificate exists for this item.", 404)
    return send_file(
        path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"certificate-{item_id}.pdf",
    )


@api.get("/jobs/<job_id>/certificates.zip")
def download_all(job_id: str):
    service = _service()
    job = service.get_job(job_id)
    if job is None:
        return _error("Job not found.", 404)
    if job["status"] == JOB_PROCESSING:
        return _error("Job is still processing. Check GET /api/jobs/{id} and try again.", 409)
    archive = service.build_zip(job_id)
    return send_file(
        archive,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"certificates-{job_id}.zip",
    )
