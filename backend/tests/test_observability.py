"""Phase 7: traces, the metrics summary, feedback, and system events."""

import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.observability.metrics import pct
from app.observability.trace import Trace, event, sink, span
from tests.conftest import FakeProvider
from tests.test_tools import _turn
from tests.test_voice_ws import _collect, _pcm, voice  # noqa: F401 - fixture


def _summary(client: TestClient, days: int = 1) -> dict:
    r = client.get("/api/metrics/summary", params={"days": days})
    assert r.status_code == 200, r.text
    return r.json()


def test_percentiles():
    assert pct([], 0.5) is None
    assert pct([10, None, 30, 20], 0.5) == 20
    assert pct(list(range(1, 101)), 0.95) == 95.0  # interpolated 95.05, one decimal


def test_spans_are_free_without_a_trace_and_recorded_with_one():
    async def work():
        async with span("outside"):
            pass
        event("nothing")
        t = Trace("chat_turn")
        sink.enabled = False  # don't queue this synthetic trace
        try:
            with t:
                async with span("retrieval") as sp:
                    sp["hits"] = 3
                event("guard.retry")
                event("guard.retry")
        finally:
            sink.enabled = True
        return t

    t = asyncio.run(work())
    assert [s["name"] for s in t.spans] == ["retrieval", "guard.retry", "guard.retry"]
    assert t.spans[0]["attrs"] == {"hits": 3} and t.attrs["events.guard.retry"] == 2
    assert t.duration_ms is not None and t.status == "ok"


def test_chat_turn_is_traced_without_content(client: TestClient, user: dict, fake: FakeProvider):
    fake.reply = "Here is the answer."
    with client.websocket_connect("/ws") as ws:
        _turn(ws, "What's the secret plan for Orion?")
    s = _summary(client)
    assert s["responses"]["turns"] == 1 and s["responses"]["errors"] == 0
    assert s["responses"]["first_token_ms"]["n"] == 1
    assert s["responses"]["completion_tokens"] > 0
    assert "fake/fake-1" in s["responses"]["by_model"]
    assert s["responses"]["cost_usd"] is None  # no price configured = local, no cost
    traces = client.get("/api/metrics/traces").json()
    turn = next(t for t in traces if t["kind"] == "chat_turn")
    names = [sp["name"] for sp in turn["spans"]]
    assert "retrieval" in names and "memory_recall" in names
    assert "Orion" not in str(turn) and "secret" not in str(turn)  # timings and counts only


def test_tool_turns_report_success_and_recovery(client: TestClient, user: dict, fake: FakeProvider):
    # First call fails (unknown task), the model recovers by creating it.
    fake.script = [[("complete_task", {"task": "nonexistent thing"})], [("create_task", {"title": "water plants"})],
                   "Added it."]
    with client.websocket_connect("/ws") as ws:
        _turn(ws, "mark water plants done")
    a = _summary(client)["agent"]
    assert a["tool_calls"] == 2 and a["failed"] == 1 and a["success_rate"] == 0.5
    assert a["turns_with_failures"] == 1 and a["failure_recovery_rate"] == 1.0
    assert {t["tool"] for t in a["per_tool"]} == {"complete_task", "create_task"}


def test_guard_retries_are_counted(client: TestClient, user: dict, fake: FakeProvider):
    fake.script = ["I've added the task to your list.", [("create_task", {"title": "x"})], "Done."]
    with client.websocket_connect("/ws") as ws:
        _turn(ws, "add x to my tasks")
    assert _summary(client)["agent"]["guards"].get("retry") == 1


def test_model_prices_give_costs(client: TestClient, user: dict, fake: FakeProvider):
    sink.prices = {"fake-1": (1.0, 2.0)}
    try:
        with client.websocket_connect("/ws") as ws:
            _turn(ws, "hello")
        r = _summary(client)["responses"]
        expected = (r["prompt_tokens"] * 1.0 + r["completion_tokens"] * 2.0) / 1_000_000
        assert abs(r["cost_usd"] - expected) < 1e-9
    finally:
        sink.prices = {}


def test_voice_turn_metrics(client: TestClient, user: dict, voice):  # noqa: F811
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "audio_utterance", "sample_rate": 16000})
        ws.send_bytes(_pcm(1.0))
        _collect(ws)
    v = _summary(client)["voice"]
    assert v["turns"] == 1 and v["stt_ms"]["n"] == 1 and v["first_audio_ms"]["n"] == 1
    assert v["stt_errors"] == 0


def test_feedback_is_owned_and_counted(client: TestClient, user: dict, fake: FakeProvider):
    with client.websocket_connect("/ws") as ws:
        events = _turn(ws, "hello")
    mid = next(e for e in events if e["type"] == "assistant_end")["message"]["id"]
    assert client.post(f"/api/messages/{mid}/feedback", json={"rating": -1, "note": "too long"}).status_code == 204
    assert _summary(client)["system"]["feedback"] == {"up": 0, "down": 1}
    cid = next(e for e in events if e["type"] == "message_saved")["conversation_id"]
    msgs = client.get(f"/api/conversations/{cid}").json()["messages"]
    assert msgs[-1]["feedback"] == -1
    assert client.post(f"/api/messages/{msgs[0]['id']}/feedback", json={"rating": 1}).status_code == 404  # user msg
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"email": "other-fb@example.com", "password": "correct-horse-battery",
                                            "display_name": "O"})
    assert client.post(f"/api/messages/{mid}/feedback", json={"rating": 1}).status_code == 404  # not theirs


def test_http_requests_and_errors_become_events(client: TestClient, user: dict):
    client.get("/api/tasks")
    client.get(f"/api/projects/{'x' * 5}")  # 404
    import logging

    logging.getLogger("app.test").error("boom happened")
    s = _summary(client)["system"]
    assert s["requests"] >= 2
    routes = {r["route"] for r in s["slowest_routes"]}
    assert "GET /api/projects/{name}" in routes or len(routes) == 8  # route templates, never raw ids
    assert any(src == "app.test" for src, _ in s["errors_by_source"])


def test_eval_reports_cannot_escape_the_results_folder(client: TestClient, user: dict):
    assert client.get("/api/metrics/evals/..%2F..%2Fapp%2Fmain.py").status_code == 404
    assert client.get("/api/metrics/evals/nope.json").status_code == 404


def test_desktop_tools_can_be_switched_off(client: TestClient, user: dict):
    from app.core.config import get_settings
    from app.tools.builtin.system import describe_automation
    from app.tools.registry import DESKTOP_TOOLS, REGISTRY, load_builtin_tools

    saved = {n: REGISTRY[n] for n in DESKTOP_TOOLS}
    s = get_settings()
    try:
        s.desktop_tools = False
        load_builtin_tools()
        assert not set(DESKTOP_TOOLS) & set(REGISTRY)
        assert "not available" in describe_automation()
        assert {t["name"] for t in client.get("/api/tools").json()}.isdisjoint(DESKTOP_TOOLS)
    finally:
        s.desktop_tools = True
        REGISTRY.update(saved)


def test_tool_calls_and_the_model_phase_are_spans(client: TestClient, user: dict, fake: FakeProvider):
    fake.script = [[("list_tasks", {})], "Nothing on your list."]
    with client.websocket_connect("/ws") as ws:
        _turn(ws, "what's on my list?")
    turn = next(t for t in client.get("/api/metrics/traces").json() if t["kind"] == "chat_turn")
    names = [s["name"] for s in turn["spans"]]
    assert "tool:list_tasks" in names and "model" in names
    model = next(s for s in turn["spans"] if s["name"] == "model")
    assert model["duration_ms"] <= turn["duration_ms"]
