"""Job orchestration.

Flow:
  1. create_job() stores the job and one item per recipient (valid rows are
     PENDING, invalid rows are FAILED with a reason) in one transaction.
  2. Each PENDING item is handed to a thread pool (or run inline when
     PROCESSING_SYNCHRONOUSLY is set, which the tests use).
  3. A worker renders the PDF and marks its item SUCCEEDED or FAILED.
     An exception in one worker is caught and recorded on that item only.
  4. When the last item finishes, the job status is finalised.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

from .db import db_session
from .validation import JobRequest, Recipient

log = logging.getLogger(__name__)

# Item statuses
PENDING = "PENDING"
PROCESSING = "PROCESSING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
ITEM_STATUSES = (PENDING, PROCESSING, SUCCEEDED, FAILED)

# Job statuses
JOB_PROCESSING = "PROCESSING"
JOB_COMPLETED = "COMPLETED"  # every recipient succeeded
JOB_COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"  # some succeeded, some failed
JOB_FAILED = "FAILED"  # nothing succeeded

Renderer = Callable[..., None]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobService:
    def __init__(
        self,
        db_path: str,
        storage_dir: str,
        renderer: Renderer,
        *,
        synchronous: bool = False,
        workers: int = 4,
    ):
        self.db_path = db_path
        self.storage_dir = storage_dir
        self.renderer = renderer
        self._executor = None if synchronous else ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="certificate-worker"
        )

    # ------------------------------------------------------------------ create
    def create_job(self, request: JobRequest) -> dict:
        job_id = uuid.uuid4().hex
        now = utcnow()
        total = len(request.accepted) + len(request.rejected)
        queued: list[tuple[int, Recipient]] = []

        with db_session(self.db_path) as conn:
            conn.execute(
                "INSERT INTO jobs (id, event_name, issued_on, status, total, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (job_id, request.event_name, request.issued_on, JOB_PROCESSING, total, now, now),
            )
            for position, recipient in request.accepted:
                cur = conn.execute(
                    "INSERT INTO items (job_id, position, name, email, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (job_id, position, recipient.name, recipient.email, PENDING, now, now),
                )
                queued.append((cur.lastrowid, recipient))
            for rejected in request.rejected:
                conn.execute(
                    "INSERT INTO items (job_id, position, name, email, status, error, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (job_id, rejected.position, rejected.name, rejected.email, FAILED, rejected.error, now, now),
                )

        # Hand work to the workers only after the rows are committed,
        # so a worker can always find its item.
        for item_id, recipient in queued:
            self._submit(job_id, item_id, recipient, request.event_name, request.issued_on)

        return self.get_job(job_id)

    def _submit(self, job_id, item_id, recipient, event_name, issued_on) -> None:
        args = (job_id, item_id, recipient, event_name, issued_on)
        if self._executor is None:
            self._process_item(*args)
        else:
            self._executor.submit(self._process_item, *args)

    # ------------------------------------------------------------ worker code
    def _process_item(self, job_id, item_id, recipient: Recipient, event_name, issued_on) -> None:
        certificate_id = uuid.uuid4().hex
        relative_path = os.path.join(job_id, f"{item_id}.pdf")
        absolute_path = os.path.join(self.storage_dir, relative_path)
        try:
            self._set_item(item_id, PROCESSING)
            self.renderer(
                absolute_path,
                recipient_name=recipient.name,
                event_name=event_name,
                issued_on=issued_on,
                certificate_id=certificate_id,
            )
            self._set_item(item_id, SUCCEEDED, certificate_id=certificate_id, certificate_path=relative_path)
        except Exception as exc:  # one bad certificate must not stop the job
            log.exception("Certificate generation failed (job=%s item=%s)", job_id, item_id)
            self._set_item(item_id, FAILED, error=f"{type(exc).__name__}: {exc}")
        finally:
            self._finalize_job_if_done(job_id)

    def _set_item(self, item_id, status, *, error=None, certificate_id=None, certificate_path=None) -> None:
        with db_session(self.db_path) as conn:
            conn.execute(
                "UPDATE items SET status = ?, error = ?, "
                "certificate_id = COALESCE(?, certificate_id), "
                "certificate_path = COALESCE(?, certificate_path), updated_at = ? "
                "WHERE id = ?",
                (status, error, certificate_id, certificate_path, utcnow(), item_id),
            )

    def _finalize_job_if_done(self, job_id) -> None:
        with db_session(self.db_path) as conn:
            counts = _item_counts(conn, job_id)
            if counts["pending"] > 0:
                return
            if counts["failed"] == 0:
                status = JOB_COMPLETED
            elif counts["succeeded"] == 0:
                status = JOB_FAILED
            else:
                status = JOB_COMPLETED_WITH_ERRORS
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                (status, utcnow(), job_id),
            )

    # ------------------------------------------------------------------ reads
    def get_job(self, job_id: str) -> dict | None:
        with db_session(self.db_path) as conn:
            job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if job is None:
                return None
            counts = _item_counts(conn, job_id)

        total = job["total"]
        done = counts["succeeded"] + counts["failed"]
        return {
            "job_id": job["id"],
            "status": job["status"],
            "event_name": job["event_name"],
            "issued_on": job["issued_on"],
            "total": total,
            "succeeded": counts["succeeded"],
            "failed": counts["failed"],
            "pending": counts["pending"],
            "progress_percent": round(100 * done / total, 1) if total else 100.0,
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
        }

    def list_items(self, job_id: str, status: str | None = None) -> list[dict]:
        sql = (
            "SELECT id, position, name, email, status, error, certificate_id FROM items WHERE job_id = ?"
        )
        params: list = [job_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY position"

        with db_session(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            {
                "item_id": row["id"],
                "position": row["position"],
                "name": row["name"],
                "email": row["email"],
                "status": row["status"],
                "error": row["error"],
                "certificate_id": row["certificate_id"],
                "certificate_url": (
                    f"/api/jobs/{job_id}/items/{row['id']}/certificate"
                    if row["status"] == SUCCEEDED
                    else None
                ),
            }
            for row in rows
        ]

    def get_certificate_path(self, job_id: str, item_id: int) -> str | None:
        with db_session(self.db_path) as conn:
            row = conn.execute(
                "SELECT certificate_path FROM items WHERE id = ? AND job_id = ? AND status = ?",
                (item_id, job_id, SUCCEEDED),
            ).fetchone()
        if row is None or not row["certificate_path"]:
            return None
        path = os.path.join(self.storage_dir, row["certificate_path"])
        return path if os.path.isfile(path) else None

    def build_zip(self, job_id: str):
        """Zip all successful certificates of a job. Returns a rewound temporary file."""
        with db_session(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, name, certificate_path FROM items "
                "WHERE job_id = ? AND status = ? ORDER BY position",
                (job_id, SUCCEEDED),
            ).fetchall()

        tmp = tempfile.TemporaryFile()
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for row in rows:
                path = os.path.join(self.storage_dir, row["certificate_path"])
                if os.path.isfile(path):
                    safe_name = re.sub(r"[^A-Za-z0-9]+", "_", row["name"] or "").strip("_")[:50]
                    archive.write(path, arcname=f"{row['id']:06d}_{safe_name}.pdf")
        tmp.seek(0)
        return tmp


def _item_counts(conn, job_id: str) -> dict:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM items WHERE job_id = ? GROUP BY status", (job_id,)
    ).fetchall()
    counts = {status: 0 for status in ITEM_STATUSES}
    for row in rows:
        counts[row["status"]] = row["n"]
    return {
        "succeeded": counts[SUCCEEDED],
        "failed": counts[FAILED],
        "pending": counts[PENDING] + counts[PROCESSING],
    }
