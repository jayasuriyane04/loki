from fastapi.testclient import TestClient


def test_crud_and_ownership(client: TestClient, user: dict):
    created = client.post("/api/conversations", json={"title": "Tarka planning"}).json()
    cid = created["id"]
    assert [c["id"] for c in client.get("/api/conversations").json()] == [cid]

    r = client.patch(f"/api/conversations/{cid}", json={"title": "Tarka v2"})
    assert r.json()["title"] == "Tarka v2"

    # A second user cannot see, rename or delete it.
    client.cookies.clear()
    client.post(
        "/api/auth/register",
        json={"email": "intruder@example.com", "password": "another-password", "display_name": "Eve"},
    )
    assert client.get(f"/api/conversations/{cid}").status_code == 404
    assert client.patch(f"/api/conversations/{cid}", json={"title": "x"}).status_code == 404
    assert client.delete(f"/api/conversations/{cid}").status_code == 404
    assert client.get("/api/conversations").json() == []

    client.cookies.clear()
    client.post("/api/auth/login", json={"email": user["email"], "password": user["password"]})
    assert client.delete(f"/api/conversations/{cid}").status_code == 204
    assert client.get(f"/api/conversations/{cid}").status_code == 404


def test_temporary_conversations_hidden_from_history(client: TestClient, user: dict):
    client.post("/api/conversations", json={"is_temporary": True})
    assert client.get("/api/conversations").json() == []


def test_models_endpoint_reports_provider(client: TestClient, user: dict):
    r = client.get("/api/models").json()
    assert r["primary"]["provider"] == "fake"
    assert r["primary"]["ok"] is True
    assert r["fallback"] is None


def test_health(client: TestClient):
    assert client.get("/api/health").json() == {"status": "ok"}
