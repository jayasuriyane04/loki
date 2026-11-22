from app.db.models import Message
from app.services.chat import build_context
from app.services.prompts import title_from_message


def _m(role: str, content: str, status: str = "complete") -> Message:
    return Message(role=role, content=content, status=status)


def test_budget_drops_oldest_turns_first():
    history = [_m("user", "a" * 50), _m("assistant", "b" * 50), _m("user", "c" * 50), _m("assistant", "d" * 50), _m("user", "new")]
    ctx = build_context("SYS", history, char_budget=110)
    assert ctx[0].role == "system"
    assert [m.content[0] for m in ctx[1:]] == ["c", "d", "n"]


def test_context_starts_with_user_and_skips_errors_and_empty():
    history = [_m("assistant", "orphan"), _m("user", "q1"), _m("assistant", "", "interrupted"), _m("assistant", "bad", "error"), _m("user", "q2")]
    ctx = build_context("SYS", history, char_budget=10_000)
    assert [(m.role, m.content) for m in ctx[1:]] == [("user", "q1"), ("user", "q2")]


def test_latest_message_always_included_even_if_over_budget():
    ctx = build_context("SYS", [_m("user", "x" * 500)], char_budget=10)
    assert len(ctx) == 2


def test_title_truncation():
    assert title_from_message("  hello   world ") == "hello world"
    assert len(title_from_message("x" * 100)) == 60
