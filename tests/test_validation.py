import re

import pytest

from certgen.validation import RequestError, parse_job_request, validate_recipient

GOOD = {"name": "Asha Patel", "email": "asha@example.com"}


def payload(**overrides):
    base = {"event_name": "Python Workshop", "recipients": [GOOD]}
    base.update(overrides)
    return base


def test_valid_request_accepts_recipients_with_positions():
    req = parse_job_request(payload(recipients=[GOOD, {"name": "Ravi", "email": "ravi@example.com"}]), max_recipients=10)
    assert [pos for pos, _ in req.accepted] == [1, 2]
    assert req.accepted[0][1].name == "Asha Patel"
    assert req.rejected == []


def test_issued_on_defaults_to_today_when_omitted():
    req = parse_job_request(payload(), max_recipients=10)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", req.issued_on)


def test_invalid_issued_on_is_rejected():
    with pytest.raises(RequestError) as exc:
        parse_job_request(payload(issued_on="08/10/2026"), max_recipients=10)
    assert exc.value.status == 400


def test_body_must_be_an_object():
    with pytest.raises(RequestError):
        parse_job_request([GOOD], max_recipients=10)


@pytest.mark.parametrize("event_name", [None, "", "   ", 42])
def test_event_name_is_required(event_name):
    with pytest.raises(RequestError, match="event_name"):
        parse_job_request(payload(event_name=event_name), max_recipients=10)


def test_recipients_must_be_non_empty_list():
    with pytest.raises(RequestError, match="recipients"):
        parse_job_request(payload(recipients=[]), max_recipients=10)


def test_too_many_recipients_is_rejected():
    recipients = [{"name": f"Person {i}", "email": f"p{i}@example.com"} for i in range(3)]
    with pytest.raises(RequestError, match="at most 2"):
        parse_job_request(payload(recipients=recipients), max_recipients=2)


def test_invalid_rows_are_reported_but_valid_rows_are_kept():
    recipients = [
        GOOD,
        {"name": "", "email": "nobody@example.com"},
        {"name": "Bad Email", "email": "not-an-email"},
        "not an object",
    ]
    req = parse_job_request(payload(recipients=recipients), max_recipients=10)
    assert [pos for pos, _ in req.accepted] == [1]
    assert [r.position for r in req.rejected] == [2, 3, 4]
    assert "name is required" in req.rejected[0].error
    assert "email is not a valid address" in req.rejected[1].error


def test_duplicate_emails_are_rejected_case_insensitively():
    recipients = [GOOD, {"name": "Asha Again", "email": "ASHA@example.com"}]
    req = parse_job_request(payload(recipients=recipients), max_recipients=10)
    assert len(req.accepted) == 1
    assert req.rejected[0].error == "duplicate email in this job"


def test_request_with_no_valid_recipients_is_422():
    with pytest.raises(RequestError) as exc:
        parse_job_request(payload(recipients=[{"name": "", "email": ""}]), max_recipients=10)
    assert exc.value.status == 422
    assert len(exc.value.details) == 1


def test_name_with_unsupported_characters_is_rejected_per_row():
    ok, error = validate_recipient({"name": "张伟", "email": "zhang@example.com"})
    assert ok is None
    assert "Latin characters only" in error


def test_latin_accented_names_are_accepted():
    recipient, error = validate_recipient({"name": "José Müller", "email": "jose@example.com"})
    assert error is None
    assert recipient.name == "José Müller"
