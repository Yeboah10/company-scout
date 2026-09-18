import time
from backend.services import password_reset


def test_issue_and_verify():
    token = password_reset.issue("test@example.com")
    assert token
    assert "." in token
    email = password_reset.verify(token)
    assert email == "test@example.com"


def test_verify_bad_token():
    assert password_reset.verify("") is None
    assert password_reset.verify("not-a-token") is None
    assert password_reset.verify("abc.def") is None


def test_verify_wrong_signature():
    token = password_reset.issue("test@example.com")
    parts = token.split(".")
    tampered = parts[0] + ".AAAA"
    assert password_reset.verify(tampered) is None


def test_verify_expired(monkeypatch):
    token = password_reset.issue("test@example.com")
    future = time.time() + password_reset.TOKEN_MAX_AGE + 60
    monkeypatch.setattr(time, "time", lambda: future)
    assert password_reset.verify(token) is None


def test_email_normalised():
    token = password_reset.issue("  Test@Example.COM  ")
    email = password_reset.verify(token)
    assert email == "test@example.com"
