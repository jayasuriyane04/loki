import json
import time

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import FakeEmbeddings, FakeProvider


def _turn(ws, content: str, conversation_id: str | None = None, wait_memory: bool = False, **extra) -> list[dict]:
    """Send a message; collect events until idle (and, if asked, until the post-turn memory update arrives)."""
    payload = {"type": "user_message", "content": content, **extra}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    ws.send_json(payload)
    events = []
    while (ev := ws.receive_json()) != {"type": "state", "state": "idle"}:
        events.append(ev)
    events.append(ev)
    if not wait_memory:
        return events
    # Post-turn memory work is a background task. Ping until its event arrives (bounded: never hang the suite).
    for _ in range(100):
        ws.send_json({"type": "ping"})
        while (ev := ws.receive_json()) != {"type": "pong"}:
            events.append(ev)
        if any(e["type"] == "memory_updated" for e in events):
            return events
        time.sleep(0.05)
    raise AssertionError(f"no memory_updated event; got {[e['type'] for e in events]}")


def _add(**kw) -> dict:
    return {"action": "add", "target": None, "kind": "profile", "importance": 0.8, "project": None, **kw}


def _wait_for_memories(client: TestClient, n: int, timeout: float = 5) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        mems = client.get("/api/memories").json()
        if len(mems) >= n:
            return mems
        time.sleep(0.05)
    return client.get("/api/memories").json()


def test_facts_are_extracted_after_a_turn_and_recalled_later(client: TestClient, user: dict, fake: FakeProvider):
    fake.extraction_ops = [[_add(content="Tony prefers concise answers with code examples.", importance=0.9)]]
    with client.websocket_connect("/ws") as ws:
        events = _turn(ws, "Please keep answers concise and show code examples.", wait_memory=True)
        update = next(e for e in events if e["type"] == "memory_updated")
        assert update["operations"][0]["action"] == "add"

        # The extractor saw the exchange with secrets redacted, in a structured-JSON call.
        prompt, schema = fake.completions[0]
        assert schema is not None and "LATEST EXCHANGE" in prompt[1].content

        # New conversation: the memory is recalled and shown to the user, and lands in the system prompt.
        events = _turn(ws, "How should you format code examples for me?")
    used = next(e for e in events if e["type"] == "memories_used")
    assert "concise answers" in used["memories"][0]["content"]
    assert {"type": "state", "state": "retrieving"} in events
    system = fake.calls[-1][0].content
    assert "<memory>\n" in system and "Tony prefers concise answers with code examples." in system

    mem = client.get("/api/memories").json()[0]
    assert mem["use_count"] >= 1 and mem["source"] == "extracted"


def test_unrelated_low_importance_memories_are_not_recalled(client: TestClient, user: dict, fake: FakeProvider):
    client.post("/api/memories", json={"content": "Tony's cat is called Pixel.", "kind": "semantic", "importance": 0.3})
    with client.websocket_connect("/ws") as ws:
        events = _turn(ws, "Explain how TCP congestion control works")
    assert not any(e["type"] == "memories_used" for e in events)
    assert "<memory>\n" not in fake.calls[-1][0].content


def test_what_do_you_remember_about_me_lists_broadly(client: TestClient, user: dict, fake: FakeProvider):
    for c in ["Tony's cat is called Pixel.", "Tony works night shifts.", "Tony is learning Rust."]:
        client.post("/api/memories", json={"content": c, "kind": "semantic", "importance": 0.3})
    with client.websocket_connect("/ws") as ws:
        events = _turn(ws, "What do you remember about me?")
    used = next(e for e in events if e["type"] == "memories_used")["memories"]
    assert len(used) == 3


def test_duplicates_are_not_stored_twice(client: TestClient, user: dict, fake: FakeProvider):
    fact = "Tony uses FastAPI for every backend project."
    fake.extraction_ops = [[_add(content=fact)], [_add(content=fact)]]
    with client.websocket_connect("/ws") as ws:
        cid = _turn(ws, "I use FastAPI for every backend.", wait_memory=True)[0]["conversation"]["id"]
        events = _turn(ws, "Yes, FastAPI for all of my backends.", cid)
    time.sleep(0.3)
    assert len(client.get("/api/memories").json()) == 1
    assert not any(e["type"] == "memory_updated" for e in events)


def test_update_and_delete_operations_use_existing_ids(client: TestClient, user: dict, fake: FakeProvider):
    client.post("/api/memories", json={"content": "Tony lives in Chennai.", "kind": "profile"})
    client.post("/api/memories", json={"content": "Tony drinks filter coffee every morning.", "kind": "profile"})
    with client.websocket_connect("/ws") as ws:
        # The extractor is shown the related memories as m1, m2...; find which label is which from the prompt.
        fake.extraction_ops = [[]]
        _turn(ws, "I moved from Chennai to Bengaluru, and forget the coffee thing.", wait_memory=False)
        time.sleep(0.3)
        listing = fake.completions[-1][0][1].content
        chennai = next(line.split("]")[0][1:] for line in listing.splitlines() if "Chennai" in line)
        coffee = next(line.split("]")[0][1:] for line in listing.splitlines() if "coffee" in line)
        fake.extraction_ops = [[
            {"action": "update", "target": chennai, "kind": "profile", "content": "Tony lives in Bengaluru.",
             "importance": 0.8, "project": None},
            {"action": "delete", "target": coffee, "kind": "profile", "content": "", "importance": 0, "project": None},
            {"action": "delete", "target": "m99", "kind": "profile", "content": "", "importance": 0, "project": None},
        ]]
        events = _turn(ws, "I moved from Chennai to Bengaluru, and forget the coffee thing.", wait_memory=True)
    ops = next(e for e in events if e["type"] == "memory_updated")["operations"]
    assert [o["action"] for o in ops] == ["update", "delete"]  # unknown id m99 ignored
    assert [m["content"] for m in client.get("/api/memories").json()] == ["Tony lives in Bengaluru."]


def test_grounding_rules():
    from app.memory.service import grounded

    user = "Arun"
    # Paraphrase of what the user said: kept.
    assert grounded("Arun is a final-year CS student in Chennai who codes in Python.",
                    "I'm a final-year computer science student in Chennai and I mostly code in Python", name=user)
    # Facts that only exist in LOKI's (wrong) reply, extracted from a user *question*: rejected.
    assert not grounded("Arun's project Tarka uses Docker for its database.",
                        "What did we decide about the database yesterday?", name=user)
    # An update may only change what the user actually said is different.
    assert not grounded("Arun's project Tarka uses Docker instead of direct PostgreSQL installation.",
                        "What did we decide about the database yesterday?",
                        base="Arun's project LOKI uses Docker instead of direct PostgreSQL installation.", name=user)
    assert grounded("Arun lives in Bengaluru.", "I moved to Bengaluru last month",
                    base="Arun lives in Chennai.", name=user)
    # Live bug: 4-letter stems let "continue" ground "containerize".
    assert not grounded("Arun decided to use Docker to containerize LOKI's database.", "Let's continue working on Tarka.",
                        base="Arun decided to use Docker for LOKI's database.", name=user)
    assert grounded("Arun codes in Go.", "I code in Go", name=user)


def test_questions_are_not_evidence_and_updates_cannot_drop_details():
    from app.memory.service import loses_detail, statements

    assert statements("Which database did I pick for it?") == ""
    assert statements("Let's continue on my app. Which database did I pick?") == "Let's continue on my app."
    assert statements("I moved to Pune. Can you update that?") == "I moved to Pune."
    # Live bug: a question rewrote "Streak uses Go and SQLite as its technology stack" and lost "Go".
    assert loses_detail("Tony's app Streak uses SQLite as its database.",
                        "Streak uses Go and SQLite as its technology stack.", "Let's continue on my app.", name="Tony")
    assert not loses_detail("Tony lives in Bengaluru.", "Tony lives in Chennai.",
                            "I moved from Chennai to Bengaluru.", name="Tony")
    # Live bug: "Let's continue working on Tarka" swapped LOKI for Tarka in a decision (one word dropped).
    assert loses_detail("Arun decided today to use Docker for Tarka's database.",
                        "Arun decided today to use Docker for LOKI's database.", "Let's continue working on Tarka.",
                        name="Arun")


def test_update_that_would_lose_details_is_saved_as_new_memory(client: TestClient, user: dict, fake: FakeProvider):
    """Live bug: 'keep answers short' was proposed as an update of the student memory and got dropped entirely."""
    client.post("/api/memories", json={"content": "Tony is a student in Chennai who prefers Python.", "kind": "profile"})
    fake.extraction_ops = [[{"action": "update", "target": "m1", "kind": "profile",
                             "content": "Tony prefers short answers.", "importance": 0.9, "project": None}]]
    with client.websocket_connect("/ws") as ws:
        events = _turn(ws, "Tony here: I prefer short answers, please.", wait_memory=True)
    assert next(e for e in events if e["type"] == "memory_updated")["operations"][0]["action"] == "add"
    assert len(client.get("/api/memories").json()) == 2


def test_appended_fact_updates_are_split_into_their_own_memory(client: TestClient, user: dict, fake: FakeProvider):
    """Live behaviour of qwen3:4b-instruct: it 'updates' by appending, e.g. '<old> and prefers short, clear answers.'"""
    old = "Tony is a final-year computer science student in Chennai who codes in Python."
    client.post("/api/memories", json={"content": old, "kind": "profile"})
    fake.extraction_ops = [[{"action": "update", "target": "m1", "kind": "profile",
                             "content": old[:-1] + " and prefers short, clear answers.", "importance": 0.9, "project": None}]]
    with client.websocket_connect("/ws") as ws:
        events = _turn(ws, "Please keep your answers short. I hate long explanations.", wait_memory=True)
    op = next(e for e in events if e["type"] == "memory_updated")["operations"][0]
    assert op["action"] == "add" and op["content"] == "Tony prefers short, clear answers."
    assert sorted(m["content"] for m in client.get("/api/memories").json()) == sorted([old, "Tony prefers short, clear answers."])


def test_pure_questions_skip_extraction(client: TestClient, user: dict, fake: FakeProvider):
    with client.websocket_connect("/ws") as ws:
        _turn(ws, "Which database did I pick for my app?")
    time.sleep(0.3)
    assert [c for c, schema in fake.completions if schema] == []


def test_update_of_an_unrelated_memory_becomes_an_add(client: TestClient, user: dict, fake: FakeProvider):
    """Live bug: 'keep answers short' was saved by overwriting the 'CS student in Chennai' memory."""
    client.post("/api/memories", json={"content": "Tony is a computer science student in Chennai.", "kind": "profile"})
    with client.websocket_connect("/ws") as ws:
        fake.extraction_ops = [[]]
        _turn(ws, "Please keep your answers short, student life is busy.")
        time.sleep(0.3)
        label = next(line.split("]")[0][1:] for line in fake.completions[-1][0][1].content.splitlines() if "Chennai" in line)
        fake.extraction_ops = [[{"action": "update", "target": label, "kind": "profile",
                                 "content": "Tony prefers short answers.", "importance": 0.9, "project": None}]]
        events = _turn(ws, "Please keep your answers short.", wait_memory=True)
    assert next(e for e in events if e["type"] == "memory_updated")["operations"][0]["action"] == "add"
    contents = sorted(m["content"] for m in client.get("/api/memories").json())
    assert contents == ["Tony is a computer science student in Chennai.", "Tony prefers short answers."]


def test_identical_rewrites_are_not_reported_as_updates(client: TestClient, user: dict, fake: FakeProvider):
    client.post("/api/memories", json={"content": "Tony is building Tarka.", "kind": "semantic"})
    fake.extraction_ops = [[{"action": "update", "target": "m1", "kind": "semantic",
                             "content": "Tony is building Tarka", "importance": 0, "project": None}]]
    with client.websocket_connect("/ws") as ws:
        events = _turn(ws, "Let's keep building Tarka")
    time.sleep(0.3)
    assert not any(e["type"] == "memory_updated" for e in events)
    assert client.get("/api/memories").json()[0]["source"] == "user_edited"  # untouched


def test_secrets_never_reach_the_extractor_or_storage(client: TestClient, user: dict, fake: FakeProvider):
    fake.extraction_ops = [[_add(content="Tony's server password is hunter2pass."), _add(content="Tony runs a home server.")]]
    with client.websocket_connect("/ws") as ws:
        _turn(ws, "My home server password is hunter2pass, remember it.", wait_memory=True)
    sent = fake.completions[0][0][1].content
    assert "hunter2pass" not in sent and "[REDACTED]" in sent
    assert [m["content"] for m in client.get("/api/memories").json()] == ["Tony runs a home server."]


def test_temporary_conversations_neither_read_nor_write_memory(client: TestClient, user: dict, fake: FakeProvider):
    client.post("/api/memories", json={"content": "Tony prefers concise answers.", "kind": "profile", "importance": 0.9})
    fake.extraction_ops = [[_add(content="Tony likes temporary chats.")]]
    with client.websocket_connect("/ws") as ws:
        events = _turn(ws, "Do you know my preferences on concise answers?", temporary=True)
    time.sleep(0.3)
    assert not any(e["type"] in ("memories_used", "memory_updated") for e in events)
    assert "<memory>\n" not in fake.calls[-1][0].content and "temporary conversation" in fake.calls[-1][0].content
    assert fake.completions == []  # extractor never called
    assert len(client.get("/api/memories").json()) == 1


def test_memory_switch_off_disables_recall_and_extraction(client: TestClient, user: dict, fake: FakeProvider):
    client.post("/api/memories", json={"content": "Tony prefers concise answers.", "kind": "profile", "importance": 0.9})
    assert client.patch("/api/settings", json={"memory_enabled": False}).json() == {"memory_enabled": False}
    with client.websocket_connect("/ws") as ws:
        events = _turn(ws, "What are my answer preferences?")
    time.sleep(0.3)
    assert not any(e["type"] == "memories_used" for e in events) and fake.completions == []
    assert client.get("/api/settings").json() == {"memory_enabled": False}


def test_chat_still_works_when_embeddings_are_down(client: TestClient, user: dict, fake: FakeProvider):
    app.state.memory.embeddings = FakeEmbeddings(fail=True)
    with client.websocket_connect("/ws") as ws:
        events = _turn(ws, "hello")
    assert any(e["type"] == "assistant_end" for e in events)
    assert not any(e["type"] == "error" for e in events)


def test_memory_api_crud_search_and_isolation(client: TestClient, user: dict):
    r = client.post("/api/memories", json={"content": "Tarka's backend uses FastAPI.", "kind": "semantic", "project": "Tarka"})
    assert r.status_code == 201
    mid = r.json()["id"]
    client.post("/api/memories", json={"content": "Tony enjoys hiking in the Western Ghats.", "kind": "profile"})

    hits = client.get("/api/memories", params={"q": "what does tarka backend use"}).json()
    assert hits[0]["id"] == mid and hits[0]["similarity"] > 0.3
    assert [m["kind"] for m in client.get("/api/memories", params={"kind": "semantic"}).json()] == ["semantic"]
    assert client.get("/api/memories/stats").json() == {"total": 2, "by_kind": {"profile": 1, "episodic": 0, "semantic": 1}}

    r = client.patch(f"/api/memories/{mid}", json={"content": "Tarka's backend uses Django.", "importance": 0.4})
    assert r.json()["content"] == "Tarka's backend uses Django." and r.json()["source"] == "user_edited"
    assert client.get("/api/memories", params={"q": "django"}).json()[0]["id"] == mid  # re-embedded

    assert client.post("/api/memories", json={"content": "my password is abc12345"}).status_code == 422
    assert client.patch(f"/api/memories/{mid}", json={"content": "token sk-abcdefghijklmnopqrstuvwxyz"}).status_code == 422

    # Another user sees nothing and cannot touch it.
    client.cookies.clear()
    client.post("/api/auth/register", json={"email": "eve2@example.com", "password": "another-password", "display_name": "Eve"})
    assert client.get("/api/memories").json() == []
    assert client.patch(f"/api/memories/{mid}", json={"importance": 1}).status_code == 404
    assert client.delete(f"/api/memories/{mid}").status_code == 404

    client.cookies.clear()
    client.post("/api/auth/login", json={"email": user["email"], "password": user["password"]})
    assert client.delete(f"/api/memories/{mid}").status_code == 204
    assert client.delete("/api/memories").status_code == 400  # needs confirm=true
    assert client.delete("/api/memories", params={"confirm": True}).json() == {"deleted": 1}
    assert client.get("/api/memories").json() == []


def test_long_conversations_are_compressed(client: TestClient, user: dict, fake: FakeProvider):
    from app.core.config import get_settings

    budget = get_settings().context_char_budget
    long_text = "x" * (budget // 6)
    with client.websocket_connect("/ws") as ws:
        cid = _turn(ws, long_text)[0]["conversation"]["id"]
        for _ in range(6):
            _turn(ws, long_text, cid)
        time.sleep(0.5)  # compression runs after the turn
        _turn(ws, "and now?", cid)
    system = fake.calls[-1][0].content
    assert "Earlier in this conversation (summarised):" in system
    summaries = [c for c, schema in fake.completions if schema is None]
    assert summaries, "summariser was called"
    # Folded turns are no longer sent verbatim: fewer messages than were exchanged.
    assert len(fake.calls[-1]) < 16
    assert json.dumps(client.get(f"/api/conversations/{cid}").json()).count("x" * 50) >= 7  # nothing deleted
