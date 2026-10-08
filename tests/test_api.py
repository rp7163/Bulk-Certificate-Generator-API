import io
import time
import zipfile

# Must match the name the test renderer (see conftest.py) treats as a failure.
SIMULATED_FAILURE_NAME = "Simulated Failure"


def create(client, recipients, **extra):
    body = {"event_name": "Python Workshop", "issued_on": "2026-10-01", "recipients": recipients, **extra}
    return client.post("/api/jobs", json=body)


def test_create_job_generates_a_certificate_for_every_recipient(client, valid_recipients):
    resp = create(client, valid_recipients)
    assert resp.status_code == 202
    assert resp.headers["Location"].startswith("/api/jobs/")

    job_id = resp.get_json()["job"]["job_id"]
    job = client.get(f"/api/jobs/{job_id}").get_json()
    assert job["status"] == "COMPLETED"
    assert job["total"] == 2
    assert job["succeeded"] == 2
    assert job["failed"] == 0
    assert job["progress_percent"] == 100.0

    items = client.get(f"/api/jobs/{job_id}/items").get_json()["items"]
    assert [i["status"] for i in items] == ["SUCCEEDED", "SUCCEEDED"]
    assert all(i["certificate_url"] for i in items)


def test_mixed_request_keeps_valid_rows_and_reports_invalid_ones(client):
    recipients = [
        {"name": "Asha Patel", "email": "asha@example.com"},
        {"name": "", "email": "nobody@example.com"},
        {"name": "Bad Email", "email": "not-an-email"},
    ]
    resp = create(client, recipients)
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["accepted"] == 1
    assert [r["position"] for r in body["rejected"]] == [2, 3]

    job_id = body["job"]["job_id"]
    job = client.get(f"/api/jobs/{job_id}").get_json()
    assert job["total"] == 3
    assert job["status"] == "COMPLETED_WITH_ERRORS"

    failed = client.get(f"/api/jobs/{job_id}/items?status=failed").get_json()["items"]
    assert len(failed) == 2
    assert all(item["error"] for item in failed)


def test_request_with_no_valid_recipients_creates_no_job(client):
    resp = create(client, [{"name": "", "email": ""}])
    assert resp.status_code == 422
    assert resp.get_json()["error"].startswith("No valid recipients")
    assert len(resp.get_json()["details"]) == 1


def test_malformed_json_is_400(client):
    resp = client.post("/api/jobs", data="not json", content_type="text/plain")
    assert resp.status_code == 400


def test_missing_event_name_is_400(client, valid_recipients):
    resp = client.post("/api/jobs", json={"recipients": valid_recipients})
    assert resp.status_code == 400
    assert "event_name" in resp.get_json()["error"]


def test_too_many_recipients_is_400(client, app, valid_recipients):
    app.config["MAX_RECIPIENTS"] = 1
    resp = create(client, valid_recipients)
    assert resp.status_code == 400
    assert "at most 1" in resp.get_json()["error"]


def test_single_certificate_failure_does_not_block_the_rest(client):
    recipients = [
        {"name": "Asha Patel", "email": "asha@example.com"},
        {"name": SIMULATED_FAILURE_NAME, "email": "broken@example.com"},
        {"name": "Ravi Shah", "email": "ravi@example.com"},
    ]
    job_id = create(client, recipients).get_json()["job"]["job_id"]

    job = client.get(f"/api/jobs/{job_id}").get_json()
    assert job["status"] == "COMPLETED_WITH_ERRORS"
    assert job["succeeded"] == 2
    assert job["failed"] == 1

    items = client.get(f"/api/jobs/{job_id}/items").get_json()["items"]
    broken = next(i for i in items if i["name"] == SIMULATED_FAILURE_NAME)
    assert broken["status"] == "FAILED"
    assert "simulated renderer failure" in broken["error"]
    assert broken["certificate_url"] is None

    ok = next(i for i in items if i["name"] == "Ravi Shah")
    assert client.get(ok["certificate_url"]).status_code == 200
    assert client.get(broken_url(job_id, broken["item_id"])).status_code == 404


def test_job_where_everything_fails_is_marked_failed(client):
    recipients = [
        {"name": SIMULATED_FAILURE_NAME, "email": "a@example.com"},
        {"name": SIMULATED_FAILURE_NAME, "email": "b@example.com"},
    ]
    job_id = create(client, recipients).get_json()["job"]["job_id"]
    assert client.get(f"/api/jobs/{job_id}").get_json()["status"] == "FAILED"


def test_certificate_download_is_a_pdf_attachment(client, valid_recipients):
    job_id = create(client, valid_recipients).get_json()["job"]["job_id"]
    item = client.get(f"/api/jobs/{job_id}/items").get_json()["items"][0]

    resp = client.get(item["certificate_url"])
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert "attachment" in resp.headers["Content-Disposition"]
    assert resp.data.startswith(b"%PDF")


def test_zip_contains_only_successful_certificates(client):
    recipients = [
        {"name": "Asha Patel", "email": "asha@example.com"},
        {"name": SIMULATED_FAILURE_NAME, "email": "broken@example.com"},
    ]
    job_id = create(client, recipients).get_json()["job"]["job_id"]

    resp = client.get(f"/api/jobs/{job_id}/certificates.zip")
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.data)) as archive:
        names = archive.namelist()
    assert len(names) == 1
    assert names[0].endswith("_Asha_Patel.pdf")


def test_items_filter_rejects_unknown_status(client, valid_recipients):
    job_id = create(client, valid_recipients).get_json()["job"]["job_id"]
    assert client.get(f"/api/jobs/{job_id}/items?status=BOGUS").status_code == 400


def test_unknown_job_is_404_json(client):
    resp = client.get("/api/jobs/does-not-exist")
    assert resp.status_code == 404
    assert resp.is_json
    assert client.get("/api/jobs/does-not-exist/items").status_code == 404
    assert client.get("/api/jobs/does-not-exist/certificates.zip").status_code == 404


def test_health_endpoint(client):
    assert client.get("/health").get_json() == {"status": "ok"}


def test_background_worker_pool_completes_the_job(threaded_app, valid_recipients):
    client = threaded_app.test_client()
    job_id = create(client, valid_recipients + [{"name": SIMULATED_FAILURE_NAME, "email": "x@example.com"}]).get_json()["job"]["job_id"]

    deadline = time.time() + 15
    job = client.get(f"/api/jobs/{job_id}").get_json()
    while job["status"] == "PROCESSING" and time.time() < deadline:
        time.sleep(0.05)
        job = client.get(f"/api/jobs/{job_id}").get_json()

    assert job["status"] == "COMPLETED_WITH_ERRORS"
    assert job["succeeded"] == 2
    assert job["failed"] == 1


def broken_url(job_id, item_id):
    return f"/api/jobs/{job_id}/items/{item_id}/certificate"
