"""Route-level tests for the new features.

These test that the routes exist and return the expected status codes.
They don't test database-dependent features (notes, password update)
since those need a live Postgres connection.
"""


def test_forgot_password_page(client):
    r = client.get("/forgot-password")
    assert r.status_code == 200
    assert "Reset your password" in r.text


def test_reset_password_page(client):
    r = client.get("/reset-password")
    assert r.status_code == 200
    assert "Set a new password" in r.text


def test_use_cases_page(client):
    r = client.get("/use-cases")
    assert r.status_code == 200
    assert "Use cases" in r.text


def test_use_cases_is_public(client):
    r = client.get("/use-cases", follow_redirects=False)
    assert r.status_code == 200


def test_forgot_password_is_public(client):
    r = client.get("/forgot-password", follow_redirects=False)
    assert r.status_code == 200


def test_reset_password_is_public(client):
    r = client.get("/reset-password", follow_redirects=False)
    assert r.status_code == 200


def test_forgot_password_post_always_succeeds(client):
    r = client.post(
        "/forgot-password",
        json={"email": "nobody@example.com"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True


def test_reset_password_post_bad_token(client):
    r = client.post(
        "/reset-password",
        json={"token": "bad-token", "password": "newpass123"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data.get("expired") is True


def test_compare_data_missing_keys(authed_client):
    r = authed_client.get("/compare-data")
    assert r.status_code == 400


def test_compare_page(client):
    r = client.get("/compare?a=x&b=y")
    assert r.status_code == 200


def test_login_has_forgot_link(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "forgot-password" in r.text


def test_index_has_use_cases_link(authed_client):
    r = authed_client.get("/")
    assert r.status_code == 200
    assert "/use-cases" in r.text


def test_index_has_notes_tab(authed_client):
    r = authed_client.get("/")
    assert r.status_code == 200
    assert "Notes" in r.text


def test_pdf_export_404(authed_client):
    r = authed_client.get("/report/nonexistent.pdf")
    assert r.status_code == 404
