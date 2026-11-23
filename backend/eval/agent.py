"""Agent evaluation: task completion (checked against real state), tool selection, unnecessary calls, execution
success and recovery from a tool failure."""

from contextlib import contextmanager
from pathlib import Path
from typing import Any

from eval.common import pct, register, turn, write_report
from eval.datasets.agent_scenarios import SCENARIOS, Scenario

FAILED = {"error", "timeout", "invalid"}


@contextmanager
def failing_once(tool_name: str | None):
    """Make a tool's first call fail with a temporary error, the way a flaky service would."""
    from app.tools.base import ToolError
    from app.tools.registry import REGISTRY

    if tool_name is None:
        yield
        return
    tool = REGISTRY[tool_name]
    original = tool.run
    state = {"failed": False}

    async def flaky(ctx, args):
        if not state["failed"]:
            state["failed"] = True
            raise ToolError("The service is temporarily unavailable. Please try again.")
        return await original(ctx, args)

    tool.run = flaky
    try:
        yield
    finally:
        tool.run = original


def run_scenario(client, sc: Scenario) -> dict[str, Any]:
    register(client, sc.id)
    if sc.setup:
        sc.setup(client)
    if sc.id == "documents":
        from eval.common import wait_documents

        wait_documents(client, 1)
    with failing_once(sc.fail_once), client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "client_info", "timezone": "Asia/Kolkata"})
        r = turn(ws, sc.prompt, approve=sc.approve)
    called = [t["tool"] for t in r["tools"]]
    ok_tools = {t["tool"] for t in r["tools"] if t["status"] == "ok"}
    executed = [t for t in r["tools"] if t["status"] != "denied"]
    unnecessary = [t for t in called if t not in sc.expect | sc.allowed]
    passed = False
    try:
        passed = bool(sc.check(client, r["reply"]))
    except Exception as e:  # noqa: BLE001
        r["check_error"] = str(e)[:200]
    if sc.approve is False:  # a denied action: the right tool must be *attempted*, and nothing done
        selected = sc.expect <= set(called) and not unnecessary
    else:
        selected = sc.expect <= ok_tools and not unnecessary
    return {
        "id": sc.id, "category": sc.category, "prompt": sc.prompt, "passed": passed, "selection_correct": selected,
        "tools": r["tools"], "unnecessary_calls": unnecessary, "approvals": r["approvals"],
        "unexpected_approval": r["approvals"] > 0 and sc.approve is None,
        "executed_ok": sum(1 for t in executed if t["status"] == "ok"), "executed": len(executed),
        "failures": sum(1 for t in r["tools"] if t["status"] in FAILED),
        "correction_shown": "(Correction:" in r["reply"], "reply": r["reply"][:600],
        "first_token_s": r["first_token_s"], "total_s": r["total_s"], "error": r["error"],
        "check_error": r.get("check_error"),
    }


def run(client, app, *, repeat: int = 1) -> Path:
    rows = [run_scenario(client, sc) | {"run": i + 1} for i in range(repeat) for sc in SCENARIOS]

    def ratio(a, b):
        return round(a / b, 3) if b else None

    recovery = [r for r in rows if r["category"] == "recovery"]
    executed = sum(r["executed"] for r in rows)
    headline = {
        "scenarios": len(SCENARIOS), "runs": len(rows),
        "task_completion": ratio(sum(r["passed"] for r in rows), len(rows)),
        "tool_selection_accuracy": ratio(sum(r["selection_correct"] for r in rows), len(rows)),
        "tool_execution_success": ratio(sum(r["executed_ok"] for r in rows), executed),
        "failure_recovery": ratio(sum(r["passed"] for r in recovery), len(recovery)),
        "unnecessary_calls": sum(len(r["unnecessary_calls"]) for r in rows),
        "unnecessary_calls_per_run": ratio(sum(len(r["unnecessary_calls"]) for r in rows), len(rows)),
        "corrections_shown": sum(r["correction_shown"] for r in rows),
        "p50_total_s": pct([r["total_s"] for r in rows], 0.5),
        "p95_total_s": pct([r["total_s"] for r in rows], 0.95),
    }
    by_category = {}
    for cat in sorted({r["category"] for r in rows}):
        rs = [r for r in rows if r["category"] == cat]
        by_category[cat] = {"runs": len(rs), "passed": sum(r["passed"] for r in rs)}
    from app.core.config import get_settings

    config = {"llm": app.state.llm.primary.model, "max_steps": get_settings().agent_max_steps, "repeat": repeat}
    return write_report("agent", config, headline, {"by_category": by_category, "runs": rows})
