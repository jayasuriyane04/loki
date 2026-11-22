from fastapi.testclient import TestClient


def test_register_sets_session_and_me_works(client: TestClient, user: dict):
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == user["email"]
    assert "password_hash" not in r.json()


def test_duplicate_email_rejected(client: TestClient, user: dict):
    r = client.post("/api/auth/register", json={**user, "email": user["email"].upper()})
    assert r.status_code == 409


def test_short_password_rejected(client: TestClient):
    r = client.post("/api/auth/register", json={"email": "a@example.com", "password": "short", "display_name": "A"})
    assert r.status_code == 422


def test_logout_revokes_session(client: TestClient, user: dict):
    cookie = client.cookies.get("loki_session")
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    # Replaying the old cookie must not work either: the session is revoked server-side.
    client.cookies.set("loki_session", cookie)
    assert client.get("/api/auth/me").status_code == 401


def test_login_wrong_password_and_success(client: TestClient, user: dict):
    client.cookies.clear()
    bad = client.post("/api/auth/login", json={"email": user["email"], "password": "wrong-password!!"})
    assert bad.status_code == 401
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever-123"})
    assert unknown.status_code == 401
    assert bad.json()["detail"] == unknown.json()["detail"]  # no account enumeration
    ok = client.post("/api/auth/login", json={"email": user["email"], "password": user["password"]})
    assert ok.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_login_rate_limited(client: TestClient, user: dict):
    client.cookies.clear()
    codes = [
        client.post("/api/auth/login", json={"email": user["email"], "password": "nope-nope-nope"}).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def test_protected_routes_require_auth(client: TestClient):
    client.cookies.clear()
    assert client.get("/api/conversations").status_code == 401
    assert client.get("/api/models").status_code == 401
