import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.llm.router import LLMRouter
from app.main import app
from tests.conftest import FakeProvider


def _collect_turn(ws) -> list[dict]:
    events = []
    while True:
        ev = ws.receive_json()
        events.append(ev)
        if ev["type"] == "state" and ev["state"] == "idle":
            return events


def test_ws_rejects_unauthenticated(client: TestClient):
    client.cookies.clear()
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_ws_rejects_foreign_origin(client: TestClient, user: dict):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()


def test_streaming_turn_persists_messages(client: TestClient, user: dict, fake: FakeProvider):
    with client.websocket_connect("/ws", headers={"origin": "http://localhost:3000"}) as ws:
        ws.send_json({"type": "user_message", "content": "Hi LOKI, what can you do?"})
        events = _collect_turn(ws)

    types = [e["type"] for e in events]
    assert types[0] == "conversation"
    assert "message_saved" in types and "assistant_start" in types and "assistant_end" in types
    tokens = "".join(e["delta"] for e in events if e["type"] == "token")
    assert tokens.strip() == "Hello from LOKI."

    end = next(e for e in events if e["type"] == "assistant_end")["message"]
    assert end["status"] == "complete"
    assert end["provider"] == "fake" and end["completion_tokens"] == 3
    assert end["latency_ms"] is not None and end["first_token_ms"] is not None

    cid = events[0]["conversation"]["id"]
    conv = client.get(f"/api/conversations/{cid}").json()
    assert conv["title"] == "Hi LOKI, what can you do?"
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]

    # System prompt is first and carries the user's name; the user turn follows.
    sent = fake.calls[0]
    assert sent[0].role == "system" and "Tony" in sent[0].content
    assert sent[-1].content == "Hi LOKI, what can you do?"


def test_follow_up_includes_history(client: TestClient, user: dict, fake: FakeProvider):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_message", "content": "My project is called Tarka."})
        cid = _collect_turn(ws)[0]["conversation"]["id"]
        ws.send_json({"type": "user_message", "conversation_id": cid, "content": "What is it called?"})
        _collect_turn(ws)
    roles = [m.role for m in fake.calls[1]]
    assert roles == ["system", "user", "assistant", "user"]
    assert fake.calls[1][1].content == "My project is called Tarka."


def test_cancel_saves_partial_as_interrupted(client: TestClient, user: dict):
    slow = FakeProvider(reply=" ".join(["word"] * 200), delay=0.02)
    app.state.llm = LLMRouter(slow, None, temperature=0, max_tokens=64)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_message", "content": "Tell me a long story"})
        seen_tokens = 0
        events = []
        while seen_tokens < 3:
            ev = ws.receive_json()
            events.append(ev)
            seen_tokens += ev["type"] == "token"
        ws.send_json({"type": "cancel"})
        events += _collect_turn(ws)
    end = next(e for e in events if e["type"] == "assistant_end")["message"]
    assert end["status"] == "interrupted"
    assert 0 < len(end["content"].split()) < 200


def test_fallback_used_when_primary_down(client: TestClient, user: dict):
    backup = FakeProvider(model="backup-1", reply="Fallback here.")
    app.state.llm = LLMRouter(FakeProvider(fail=True), backup, temperature=0, max_tokens=64)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_message", "content": "hello"})
        events = _collect_turn(ws)
    start = next(e for e in events if e["type"] == "assistant_start")
    assert start["model"] == "backup-1" and start["fell_back"] is True


def test_all_providers_down_reports_error(client: TestClient, user: dict):
    app.state.llm = LLMRouter(FakeProvider(fail=True), None, temperature=0, max_tokens=64)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_message", "content": "hello"})
        events = _collect_turn(ws)
    err = next(e for e in events if e["type"] == "error")
    assert err["code"] == "llm_unavailable"
    assert not any(e["type"] == "assistant_end" for e in events)


def test_bad_messages_rejected(client: TestClient, user: dict):
    with client.websocket_connect("/ws") as ws:
        ws.send_text("not json")
        assert ws.receive_json()["code"] == "bad_request"
        ws.send_json({"type": "user_message", "content": ""})
        assert ws.receive_json()["code"] == "bad_request"
        ws.send_json({"type": "user_message", "conversation_id": "00000000-0000-0000-0000-000000000000", "content": "x"})
        events = _collect_turn(ws)
        assert any(e.get("code") == "not_found" for e in events)
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_empty_reply_reported(client: TestClient, user: dict):

    class ReasonOnly(FakeProvider):
        async def stream_chat(self, messages, *, temperature, max_tokens, tools=None):
            from app.llm.base import StreamChunk

            yield StreamChunk(reasoning=True)
            yield StreamChunk(done=True)

    app.state.llm = LLMRouter(ReasonOnly(), None, temperature=0, max_tokens=64)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_message", "content": "hello"})
        events = _collect_turn(ws)
    assert {"type": "state", "state": "thinking"} in events
    assert any(e.get("code") == "empty_reply" for e in events)
    end = next(e for e in events if e["type"] == "assistant_end")["message"]
    assert end["status"] == "error"
