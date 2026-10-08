"""Validation of certificate generation requests.

Design rule: a *malformed request* (wrong JSON shape, missing event name, too
many recipients, no valid recipients at all) is rejected as a whole. An
*invalid recipient row* is recorded as FAILED with a reason, and the valid
rows in the same request are still generated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EVENT_NAME_LENGTH = 200
MAX_NAME_LENGTH = 120
MAX_EMAIL_LENGTH = 254


class RequestError(Exception):
    """The whole request is unusable."""

    def __init__(self, message: str, status: int = 400, details: list | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.details = details or []


@dataclass(frozen=True)
class Recipient:
    name: str
    email: str


@dataclass(frozen=True)
class RejectedRecipient:
    position: int  # 1-based index of the row in the request
    name: str | None
    email: str | None
    error: str

    def to_dict(self) -> dict:
        return {"position": self.position, "name": self.name, "email": self.email, "error": self.error}


@dataclass(frozen=True)
class JobRequest:
    event_name: str
    issued_on: str
    accepted: list[tuple[int, Recipient]]  # (position, recipient)
    rejected: list[RejectedRecipient]


def is_renderable(text: str) -> bool:
    """The built-in PDF font supports Windows-1252 (Western European) characters only."""
    try:
        text.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def parse_job_request(payload, max_recipients: int) -> JobRequest:
    if not isinstance(payload, dict):
        raise RequestError("Request body must be a JSON object.")

    event_name = payload.get("event_name")
    if not isinstance(event_name, str) or not event_name.strip():
        raise RequestError("'event_name' is required and must be a non-empty string.")
    event_name = event_name.strip()
    if len(event_name) > MAX_EVENT_NAME_LENGTH:
        raise RequestError(f"'event_name' must be at most {MAX_EVENT_NAME_LENGTH} characters.")
    if not is_renderable(event_name):
        raise RequestError("'event_name' contains characters the certificate font cannot render (Latin characters only).")

    issued_on = _parse_issued_on(payload.get("issued_on"))

    recipients = payload.get("recipients")
    if not isinstance(recipients, list) or not recipients:
        raise RequestError("'recipients' is required and must be a non-empty list.")
    if len(recipients) > max_recipients:
        raise RequestError(f"A single job may contain at most {max_recipients} recipients (got {len(recipients)}).")

    accepted: list[tuple[int, Recipient]] = []
    rejected: list[RejectedRecipient] = []
    seen_emails: set[str] = set()

    for position, raw in enumerate(recipients, start=1):
        recipient, error = validate_recipient(raw)
        if recipient is None:
            rejected.append(RejectedRecipient(position, _field(raw, "name"), _field(raw, "email"), error))
            continue
        key = recipient.email.lower()
        if key in seen_emails:
            rejected.append(RejectedRecipient(position, recipient.name, recipient.email, "duplicate email in this job"))
            continue
        seen_emails.add(key)
        accepted.append((position, recipient))

    if not accepted:
        raise RequestError(
            "No valid recipients were provided, so no job was created.",
            status=422,
            details=[r.to_dict() for r in rejected],
        )
    return JobRequest(event_name=event_name, issued_on=issued_on, accepted=accepted, rejected=rejected)


def validate_recipient(raw) -> tuple[Recipient | None, str | None]:
    """Return (recipient, None) when valid, or (None, error_message) when not."""
    if not isinstance(raw, dict):
        return None, "recipient must be an object with 'name' and 'email'"

    errors: list[str] = []

    name = raw.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        errors.append("name is required")
    elif len(name) > MAX_NAME_LENGTH:
        errors.append(f"name must be at most {MAX_NAME_LENGTH} characters")
    elif not is_renderable(name):
        errors.append("name contains characters the certificate font cannot render (Latin characters only)")

    email = raw.get("email")
    email = email.strip() if isinstance(email, str) else ""
    if not email:
        errors.append("email is required")
    elif len(email) > MAX_EMAIL_LENGTH or not EMAIL_PATTERN.match(email):
        errors.append("email is not a valid address")

    if errors:
        return None, "; ".join(errors)
    return Recipient(name=name, email=email), None


def _field(raw, key: str) -> str | None:
    if isinstance(raw, dict) and isinstance(raw.get(key), str):
        return raw[key]
    return None


def _parse_issued_on(value) -> str:
    if value is None or value == "":
        return date.today().isoformat()
    if not isinstance(value, str):
        raise RequestError("'issued_on' must be a string in YYYY-MM-DD format.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise RequestError("'issued_on' must be a valid date in YYYY-MM-DD format.") from None
