"""INV-2: no PII reaches the model provider."""

from app.core.redaction import redact


def test_email_is_redacted() -> None:
    r = redact("Contact me at savage@mylaurier.ca about CP104.")
    assert "savage@mylaurier.ca" not in r.text
    assert "CP104" in r.text


def test_student_number_is_redacted() -> None:
    r = redact("My student number is 123456789.")
    assert "123456789" not in r.text


def test_phone_is_redacted() -> None:
    r = redact("Call 519-884-0710 ext 1234.")
    assert "519-884-0710" not in r.text


def test_placeholders_restore_exactly() -> None:
    original = "Email savage@mylaurier.ca or call 519-884-0710."
    r = redact(original)
    assert r.restore(r.text) == original


def test_course_codes_survive_redaction() -> None:
    """Course codes look like identifiers but must reach the model intact."""
    r = redact("Do I need CP164 before CP264?")
    assert "CP164" in r.text and "CP264" in r.text
