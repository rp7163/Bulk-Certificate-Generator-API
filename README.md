# Bulk Certificate Generator

A Flask backend that accepts a **bulk** certificate request (many recipients in one HTTP call), validates each recipient, generates a PDF certificate per valid recipient from a single predefined template, tracks progress per job and per recipient, and lets the client download individual certificates or a ZIP of all of them.

- **Language / framework:** Python 3.10+, Flask
- **Database:** SQLite (standard library, no server to install)
- **PDF generation:** ReportLab
- **Tests:** pytest (34 tests)

---

## 1. Setup (Windows 11, PowerShell)

Only two things need to be installed: **Python** and this project's three pip packages (Flask, ReportLab, pytest). SQLite ships with Python.

1. **Install Python 3.12 or newer** from https://www.python.org/downloads/windows/.
   During installation, tick **"Add python.exe to PATH"**.
   Check it in a new PowerShell window:
   ```powershell
   py --version
   ```

2. **Open a terminal in the project folder** (`certificate-generator`) and create a virtual environment:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
   If PowerShell blocks the activation script, run this once and try again:
   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```

3. **Install the dependencies:**
   ```powershell
   pip install -r requirements-dev.txt
   ```
   `requirements-dev.txt` includes `requirements.txt` (Flask, ReportLab) plus pytest.

macOS/Linux work the same way, using `python3 -m venv .venv` and `source .venv/bin/activate`.

### Configuration (optional)

All settings have defaults. Override them with environment variables if needed:

| Variable | Default | Meaning |
|---|---|---|
| `CERT_DB_PATH` | `storage/app.db` | SQLite database file |
| `CERT_CERT_DIR` | `storage/certificates` | Where generated PDFs are stored |
| `CERT_MAX_RECIPIENTS` | `5000` | Maximum recipients per job request |
| `CERT_WORKER_THREADS` | `4` | Background threads that render certificates |

---

## 2. Run the application

```powershell
python run.py
```

The API is now at `http://127.0.0.1:5000`. Check it with:

```powershell
curl.exe http://127.0.0.1:5000/health
```

Expected response: `{"status": "ok"}`

The database and certificate folders are created automatically on first start. Stop the server with `Ctrl+C`.

---

## 3. Run the tests

```powershell
python -m pytest -v
```

The tests cover:

| Area | Test file |
|---|---|
| Creating a generation job, job status, progress | `tests/test_api.py` |
| Input validation (request level and per-recipient) | `tests/test_validation.py` |
| Certificate generation (PDF output, font fitting) | `tests/test_certificate.py` |
| Handling an individual certificate failure | `tests/test_api.py::test_single_certificate_failure_does_not_block_the_rest` |
| Retrieving certificates (single PDF and ZIP) | `tests/test_api.py` |
| Real background thread pool | `tests/test_api.py::test_background_worker_pool_completes_the_job` |

Tests use a temporary database and output folder, so they never touch your real `storage/` data.

---

## 4. API reference

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/jobs` | Submit a bulk certificate job. Returns `202 Accepted`. |
| `GET` | `/api/jobs/{job_id}` | Job status and progress counts |
| `GET` | `/api/jobs/{job_id}/items` | Per-recipient results. Optional `?status=SUCCEEDED` or `?status=FAILED` filter. |
| `GET` | `/api/jobs/{job_id}/items/{item_id}/certificate` | Download one certificate (PDF) |
| `GET` | `/api/jobs/{job_id}/certificates.zip` | Download all successful certificates as a ZIP |
| `GET` | `/health` | Health check |

### Submit a certificate generation request

**Request body (JSON):**

| Field | Required | Notes |
|---|---|---|
| `event_name` | yes | Course or event name printed on the certificate (max 200 chars) |
| `issued_on` | no | `YYYY-MM-DD`. Defaults to today. |
| `recipients` | yes | Non-empty list of objects with `name` and `email` |

Each recipient:
- `name`: required, max 120 characters
- `email`: required, must look like an address, unique within the job (case-insensitive)
- Names and the event name must use Latin characters (Windows-1252), such as `José Müller`. The built-in certificate font cannot draw other scripts.

**PowerShell:**

```powershell
$body = @{
  event_name = "Python Workshop"
  issued_on  = "2026-10-01"
  recipients = @(
    @{ name = "Asha Patel"; email = "asha@example.com" },
    @{ name = "Ravi Shah";  email = "ravi@example.com" }
  )
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5000/api/jobs `
  -ContentType "application/json" -Body $body
```

**curl (Windows 10/11 `curl.exe`, macOS, Linux):**

```bash
curl -X POST http://127.0.0.1:5000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"event_name":"Python Workshop","issued_on":"2026-10-01","recipients":[{"name":"Asha Patel","email":"asha@example.com"},{"name":"Ravi Shah","email":"ravi@example.com"}]}'
```

**Example response (`202 Accepted`):**

```json
{
  "accepted": 2,
  "job": {
    "job_id": "7356c4228057433fbb657a74155924e0",
    "status": "PROCESSING",
    "event_name": "Python Workshop",
    "issued_on": "2026-10-01",
    "total": 2,
    "succeeded": 0,
    "failed": 0,
    "pending": 2,
    "progress_percent": 0.0,
    "created_at": "2026-10-08T11:41:30+00:00",
    "updated_at": "2026-10-08T11:41:30+00:00"
  },
  "links": {
    "self": "/api/jobs/7356c4228057433fbb657a74155924e0",
    "items": "/api/jobs/7356c4228057433fbb657a74155924e0/items",
    "certificates_zip": "/api/jobs/7356c4228057433fbb657a74155924e0/certificates.zip"
  },
  "rejected": []
}
```

Generation runs in the background, so `status` starts as `PROCESSING`. Poll the job endpoint until it becomes final.

**Invalid rows** are not fatal. For example, if one of three recipients has no name, the response is still `202`. The valid rows are generated, and the invalid row appears in `rejected` and in the items list as `FAILED` with a reason.

**Request-level errors** (the whole request is rejected):

| Situation | Status |
|---|---|
| Body is not valid JSON | `400` |
| `event_name` missing, `issued_on` malformed, `recipients` missing or empty, too many recipients | `400` |
| Every recipient is invalid, so no job is created | `422` (the response lists each row's error in `details`) |

### Check job status

```bash
curl http://127.0.0.1:5000/api/jobs/<job_id>
```

```json
{
  "job_id": "7356c4228057433fbb657a74155924e0",
  "status": "COMPLETED_WITH_ERRORS",
  "event_name": "Python Workshop",
  "issued_on": "2026-10-01",
  "total": 3,
  "succeeded": 2,
  "failed": 1,
  "pending": 0,
  "progress_percent": 100.0,
  "created_at": "2026-10-08T11:41:30+00:00",
  "updated_at": "2026-10-08T11:41:30+00:00"
}
```

**Job statuses:**

| Status | Meaning |
|---|---|
| `PROCESSING` | Some items are still pending or being generated |
| `COMPLETED` | Every recipient got a certificate |
| `COMPLETED_WITH_ERRORS` | Some succeeded and some failed |
| `FAILED` | Nothing succeeded |

`progress_percent` counts finished items (succeeded or failed) out of `total`.

### See which recipients succeeded or failed

```bash
curl http://127.0.0.1:5000/api/jobs/<job_id>/items
curl "http://127.0.0.1:5000/api/jobs/<job_id>/items?status=FAILED"
```

```json
{
  "job_id": "7356c4228057433fbb657a74155924e0",
  "count": 3,
  "items": [
    {"item_id": 1, "position": 1, "name": "Asha Patel", "email": "asha@example.com",
     "status": "SUCCEEDED", "error": null, "certificate_id": "24cd08...",
     "certificate_url": "/api/jobs/7356c4228057433fbb657a74155924e0/items/1/certificate"},
    {"item_id": 3, "position": 3, "name": "", "email": "x@example.com",
     "status": "FAILED", "error": "name is required", "certificate_id": null,
     "certificate_url": null}
  ]
}
```

`position` is the row number in the request (1-based), so the client can match results back to its own list.

### Retrieve generated certificates

Download one certificate (PDF):

```powershell
curl.exe -o certificate-1.pdf http://127.0.0.1:5000/api/jobs/<job_id>/items/1/certificate
```

Download all successful certificates as a ZIP. This returns `409` while the job is still `PROCESSING`:

```powershell
curl.exe -o certificates.zip http://127.0.0.1:5000/api/jobs/<job_id>/certificates.zip
```

A failed item has no certificate, so its certificate URL returns `404`.

---

## 5. Architecture

```
certificate-generator/
├── run.py                  # starts the dev server
├── certgen/
│   ├── __init__.py         # application factory: create_app()
│   ├── config.py           # settings from environment variables
│   ├── routes.py           # HTTP endpoints (translate HTTP <-> service calls)
│   ├── validation.py       # request and recipient validation rules
│   ├── jobs.py             # job orchestration, status tracking, worker dispatch
│   ├── certificate.py      # the single certificate template (ReportLab)
│   └── db.py               # SQLite schema and connection handling
├── tests/                  # pytest suite
├── requirements.txt        # runtime dependencies
└── requirements-dev.txt    # adds pytest
```

**Layering:** routes never touch SQL or PDF code directly. They call `validation.parse_job_request()` and `JobService`. This keeps each piece testable on its own.

### Job processing flow

1. `POST /api/jobs` parses the JSON and validates the request.
2. Each recipient row is validated. Valid rows are stored as `PENDING`. Invalid rows are stored as `FAILED` with the reason.
3. The job and all of its items are written in **one database transaction**. A job is never half-created.
4. After the commit, each `PENDING` item is handed to a **thread pool** (4 threads by default). The HTTP request returns `202` immediately.
5. A worker marks its item `PROCESSING`, renders the PDF, and marks it `SUCCEEDED`. If rendering raises an exception, the worker catches it, marks that item `FAILED` with the error text, and moves on.
6. After each item finishes, the worker checks whether any items are still unfinished. When none remain, it sets the final job status.

### Certificate generation flow

`render_certificate()` draws one A4-landscape template with a double border, a title, the recipient's name, the event name, the issue date, and a unique certificate ID. Long names and event names are shrunk to fit the page width, down to a 12pt minimum. The PDF is written to `<file>.pdf.tmp` and then renamed, so a crash cannot leave a corrupt certificate behind.

### Storage layout

```
storage/
├── app.db                          # SQLite: jobs and items tables
└── certificates/
    └── <job_id>/
        ├── 1.pdf                   # one file per item (named by item id)
        └── 2.pdf
```

---

## 6. Design decisions

### Why the work runs in the background instead of inside the request
A job can contain thousands of recipients. Rendering each PDF takes tens of milliseconds, so a synchronous request could run for minutes and tie up the client and the server. The API therefore returns `202 Accepted` with a job ID right away, and the client polls for status. This is the main reason the API was designed around jobs.

Alternatives I considered:
- **Synchronous generation in the request:** simplest, but the request times out for large jobs and cannot report progress.
- **Celery + Redis (or RabbitMQ):** the standard production choice with retries, multiple machines, and scheduling. It needs extra services to install and run, which conflicts with the goal of minimal setup on Windows. I left it as future work.
- **Python `ThreadPoolExecutor` (chosen):** no extra services, and enough for one process. Jobs run in the background and still survive long requests.

### Why SQLite via the standard library instead of an ORM
SQLite is built into Python, so there's nothing extra to download. The schema is two tables, and raw SQL keeps every query visible and easy to explain. Each thread opens its own short-lived connection, which avoids sharing a connection across threads. The database is the source of truth for status, so the design doesn't depend on any in-memory state.

Alternatives: SQLAlchemy (more portable across databases, but another dependency to learn and install) and PostgreSQL (better for multi-server deployments, but requires installing a database server).

### Why a failure in one certificate does not stop the job
Each item runs inside its own `try/except` in the worker. The exception is recorded on that item (`error` field), and processing continues. The job status then reflects the outcome: `COMPLETED_WITH_ERRORS` when some items fail, and `FAILED` only when nothing succeeds. Tests simulate a renderer crash for one recipient to verify this.

### Why invalid rows are recorded instead of rejecting the whole request
The brief says invalid data should be handled "appropriately" and should not block valid certificates. Rejecting the whole request for one bad email would force the client to resend thousands of rows. Instead, the valid rows proceed, and each invalid row is recorded with a clear reason. The one exception: if **every** row is invalid, the request is rejected with `422`, since there is nothing to generate.

### Why the PDF is written to a temporary file first
`render_certificate()` writes `<name>.pdf.tmp` and renames it to `<name>.pdf` only when the PDF is complete. If the process crashes midway, nothing is left looking like a finished certificate, and the item stays in its previous state.

### Why ReportLab with the built-in Helvetica font
ReportLab is a pure-Python PDF library, so it installs with a single `pip install` on Windows. The built-in Helvetica font needs no font files, but it only covers Western European (Windows-1252) characters. The validator rejects names that the font can't render, with a clear per-row error. Supporting other scripts requires embedding a Unicode TTF font, which is listed under future scope.

### Why Flask
Flask is a single small dependency, which best fits the requirement of minimal extra downloads. Its request handling and blueprints are enough for this API. FastAPI would also work and gives automatic OpenAPI docs, but it adds more dependencies (Pydantic, Uvicorn). Django would add much more structure than a single-endpoint-group service needs.

### Design choice: one template
The brief says a single predefined template is enough. The template is one function in `certificate.py`. Adding a second template would mean adding a template parameter to the request and a lookup, which is straightforward but out of scope.

---

## 7. Known limitations

- **Restart behaviour:** if the server stops while a job is `PROCESSING`, those items stay `PROCESSING` and are not resumed. Re-submitting the job is the workaround.
- **Single process:** the thread pool lives inside one server process. Running several server processes would split job processing across them, and the status tracking would still work, but there's no shared queue.
- **Latin characters only:** names and event names must be encodable in Windows-1252. Other scripts are rejected per row.
- **ZIP is built in a temporary file** on the server for each request. This is fine for a single job but not cached.
- **No authentication.** Anyone who can reach the server can submit jobs and download certificates.
- **Email is validated for format only.** The service does not send the certificates or confirm that addresses exist.
- **Development server:** `run.py` uses Flask's built-in server. For production, use a WSGI server such as Waitress (works on Windows) or Gunicorn (Linux).

---

## 8. Possible next steps

- Persist the work queue (for example, a `PENDING` scan on startup) so jobs resume after a restart, or move to Celery/RQ for multi-process processing.
- Embed a Unicode font (such as Noto Sans) to support names in Gujarati, Hindi, and other scripts.
- Add authentication (API keys per client) and per-client job isolation.
- Email each certificate to its recipient as a follow-up job step.
- Make the template configurable (logo, signature, colours) through a settings file.
- Add pagination to the items endpoint for very large jobs.
- Add a cancel endpoint for running jobs.
- Generate OpenAPI documentation automatically.
