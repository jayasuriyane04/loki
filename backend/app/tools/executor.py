"""Validates, authorises, runs and logs tool calls. The model only *requests*; this decides."""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.db.models import ToolExecution
from app.llm.base import ToolCall
from app.observability.trace import span
from app.tools.base import Tool, ToolContext, ToolError
from app.tools.registry import REGISTRY

log = logging.getLogger(__name__)
MAX_RESULT_CHARS = 12_000


@dataclass
class Prepared:
    call: ToolCall
    tool: Tool | None
    args: BaseModel | None
    mode: str  # auto | confirm | off | invalid
    error: str | None = None


@dataclass
class Outcome:
    call: ToolCall
    status: str  # ok | error | denied | timeout | invalid | disabled
    content: str  # sent back to the model
    summary: str
    permission: str
    approved: bool | None
    duration_ms: int
    data: dict[str, Any] | None = None

    def step(self) -> dict[str, Any]:
        """Compact record for the UI / message history."""
        return {"id": self.call.id, "tool": self.call.name, "args": self.call.arguments, "status": self.status,
                "summary": self.summary, "approved": self.approved, "duration_ms": self.duration_ms, "data": self.data}


def prepare(call: ToolCall, prefs: dict[str, str] | None) -> Prepared:
    tool = REGISTRY.get(call.name)
    if tool is None:
        return Prepared(call, None, None, "invalid", f"There is no tool called {call.name!r}.")
    mode = tool.effective(prefs)
    if mode == "off":
        return Prepared(call, tool, None, "off", "The user has switched this tool off.")
    try:
        args = tool.input_model.model_validate(call.arguments or {})
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(str(x) for x in err['loc']) or 'input'}: {err['msg']}" for err in e.errors())
        return Prepared(call, tool, None, "invalid", f"Invalid arguments for {call.name}: {problems}")
    return Prepared(call, tool, args, mode)


def describe(p: Prepared) -> str:
    """Human-readable line for an approval card."""
    args = ", ".join(f"{k}={v!r}" for k, v in (p.args.model_dump(exclude_none=True) if p.args else {}).items())
    return f"{p.call.name}({args})"


async def execute(p: Prepared, ctx: ToolContext, *, approved: bool | None) -> Outcome:
    async with span(f"tool:{p.call.name}") as sp:
        out = await _execute(p, ctx, approved=approved)
        sp["status"] = out.status
    return out


async def _execute(p: Prepared, ctx: ToolContext, *, approved: bool | None) -> Outcome:
    start = time.perf_counter()
    tool = p.tool
    permission = tool.permission if tool else "read"

    def done(status: str, content: str, summary: str, data: dict | None = None) -> Outcome:
        return Outcome(p.call, status, content[:MAX_RESULT_CHARS], summary[:300], permission,
                       approved if p.mode == "confirm" else None, int((time.perf_counter() - start) * 1000), data)

    if p.mode == "invalid":
        out = done("invalid", p.error or "Invalid tool call.", f"{p.call.name}: invalid call")
    elif p.mode == "off":
        out = done("disabled", p.error or "Tool disabled.", f"{p.call.name} is switched off")
    elif p.mode == "confirm" and approved is not True:
        out = done("denied", "The user did NOT approve this action, so it was not done. Don't retry it; tell the "
                   "user it wasn't done and ask how they'd like to proceed.", f"{p.call.name}: not approved")
    else:
        assert tool is not None and p.args is not None
        try:
            result = await asyncio.wait_for(tool.run(ctx, p.args), timeout=tool.timeout_s)
            out = done("ok", result.content, result.summary, result.data)
        except ToolError as e:
            out = done("error", f"Tool error: {e}", f"{p.call.name} failed: {e}")
        except TimeoutError:
            out = done("timeout", f"The tool timed out after {tool.timeout_s:.0f} s.", f"{p.call.name} timed out")
        except Exception as e:  # noqa: BLE001 - never crash the agent because one tool broke
            log.exception("tool crashed", extra={"tool": p.call.name})
            out = done("error", f"The tool failed unexpectedly ({type(e).__name__}).", f"{p.call.name} failed")

    await _log(ctx, out)
    log.info("tool call", extra={"tool": p.call.name, "status": out.status, "ms": out.duration_ms, "approved": out.approved})
    return out


async def _log(ctx: ToolContext, o: Outcome) -> None:
    try:
        async with ctx.sessions() as db:
            db.add(ToolExecution(
                user_id=ctx.user_id, conversation_id=ctx.conversation_id, tool=o.call.name,
                arguments=o.call.arguments or {}, permission=o.permission, status=o.status, approved=o.approved,
                summary=o.summary, result=o.content[:4000] if o.status == "ok" else None,
                error=o.content[:2000] if o.status != "ok" else None, duration_ms=o.duration_ms,
            ))
            await db.commit()
    except Exception:  # noqa: BLE001 - logging must not break the turn
        log.exception("could not record tool execution")
