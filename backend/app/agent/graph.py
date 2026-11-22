"""LOKI's agent as a LangGraph state machine.

    START → model ──(tool calls?)──▶ approve ──▶ tools ──▶ model … ──(no tool calls / step limit)──▶ END

- model:   streams the LLM reply (text goes straight to the user) and collects tool calls.
- approve: validates each call and, for tools that need confirmation, pauses the graph with `interrupt()` until
           the user approves or denies. No side effects happen here, so re-running this node on resume is safe.
- tools:   executes the approved/allowed calls (validated, time-limited, logged) and feeds results back.

Messages in the state are plain dicts so the checkpointer can store them; live objects (LLM, socket, DB access)
travel in the per-run `context`, which is never checkpointed.
"""

import asyncio
import logging
import re
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from app.llm.base import ChatMessage, StreamChunk, ToolCall
from app.llm.router import LLMRouter, StreamStarted
from app.tools.base import ToolContext, ToolError
from app.tools.executor import Outcome, Prepared, describe, execute, prepare

log = logging.getLogger(__name__)
Emit = Callable[[Any], Awaitable[None]]  # forwards StreamStarted/StreamChunk to the turn
Send = Callable[[dict[str, Any]], Awaitable[None]]  # WebSocket events


class AgentState(TypedDict, total=False):
    messages: list[dict]
    pending: list[dict]  # tool calls requested by the last model step
    decisions: dict[str, bool]  # call id → approved?
    rejected: dict[str, str]  # call id → why it can't be done (found before asking the user)
    steps: int
    retry: bool  # the model claimed an action without doing it; send it back once


# Phrases that assert an action was performed. If one appears while no tool succeeded this turn, the model is
# describing an action it never took (small models imitate earlier replies) — that must not reach the user unchallenged.
CLAIMED_ACTION = re.compile(
    r"\b(?:(?:task|reminder|event|note|item|notification)s?\s+(?:has been |have been |was |were )?"
    r"(?:created|added|deleted|removed|completed|set|saved|scheduled|cancelled|updated|sent)"
    r"|i(?:'ve| have)\s+(?:added|created|deleted|removed|set|saved|scheduled|cancell?ed|completed|marked|opened|ran|"
    r"sent|notified)"
    r"|(?:has|have) been (?:added|created|deleted|removed|saved|scheduled|cancell?ed|marked)"
    r"|(?:is|are) (?:now )?(?:deleted|removed)"
    r"|permanently (?:removed|deleted))\b",
    re.I,
)
# "I'll retrieve the tasks now" / "Let me check…" followed by… nothing: the turn would end with a broken promise.
PROMISED_ACTION = re.compile(
    r"\b(?:i(?:'ll| will)|let me|i am going to|i'm going to)\s+(?:now\s+|first\s+|quickly\s+)?"
    r"(?:retrieve|check|list|look\s+up|fetch|get|search|find|delete|remove|create|add|set|schedule|cancel|update|"
    r"mark|run|open|read|save|try)\b",
    re.I,
)


@dataclass
class AgentContext:
    llm: LLMRouter
    tools: list[dict]  # function schemas offered to the model
    prefs: dict[str, str] | None
    tool_ctx: ToolContext
    send: Send
    emit: Emit
    max_steps: int
    outcomes: list[Outcome] = field(default_factory=list)
    started: bool = False
    has_text: bool = False  # something has been said already (later steps start on a new paragraph)
    tail: str = ""  # last few characters sent, to avoid stacking blank lines between steps
    nudged: bool = False  # the claimed-action safety net fires at most once per turn
    prior_ok: list[dict] = field(default_factory=list)  # successful tool steps from earlier turns of this chat
    user_request: str = ""  # this turn's user message (for the completion check)
    requests_checked: bool = False


def to_dict(m: ChatMessage) -> dict:
    return {"role": m.role, "content": m.content, "tool_name": m.tool_name, "tool_call_id": m.tool_call_id,
            "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in m.tool_calls]}


def to_msg(d: dict) -> ChatMessage:
    return ChatMessage(d["role"], d.get("content") or "", tuple(ToolCall(**c) for c in d.get("tool_calls") or ()),
                       d.get("tool_name"), d.get("tool_call_id"))


# Which successful tools back which kind of claim. Live bug: after a successful *list_tasks*, the model wrote
# "I've deleted it" without ever calling delete_task — any-success was not enough evidence.
_CLAIM_KINDS = [
    (re.compile(r"delet|remov", re.I), ("delete_",)),
    (re.compile(r"cancell?ed", re.I), ("cancel_",)),
    (re.compile(r"complet|marked", re.I), ("complete_",)),
    (re.compile(r"notif|\bsent\b", re.I), ("notify_",)),
    (re.compile(r"creat|added|\bset\b|saved|scheduled", re.I), ("create_", "notify_")),
    (re.compile(r"opened", re.I), ("open_",)),
    (re.compile(r"\bran\b", re.I), ("run_",)),
]


_QUOTED = re.compile(r"[“\"']([^”\"']{2,80})[”\"']")


# Explicit requests in the user's message → the tool that fulfils them. Live bug: asked to "save a summary as a
# note, and notify me when it's done", the model researched well, answered, and silently did neither.
_REQUESTS = [
    (re.compile(r"\b(save|store|write)\b.{0,60}\b(note|summary|report)\b|\bas a note\b", re.I), "create_note"),
    (re.compile(r"\b(notify|ping|alert) me\b|\blet me know when\b", re.I), "notify_user"),
    # "remind me what/how ..." asks for information, not a reminder.
    (re.compile(r"\bremind me\b(?!,?\s+(what|how|who|why|where|which|whether|if|of)\b)", re.I), "create_reminder"),
    (re.compile(r"\badd\b.{0,60}\b(to )?(my )?(task|to-?do)s?\b", re.I), "create_task"),
    (re.compile(r"\b(add|put|schedule)\b.{0,60}\b(calendar|event|meeting)\b", re.I), "create_event"),
]


def unfulfilled_requests(user_text: str, outcomes: list[Outcome], offered: set[str]) -> list[str]:
    """Tools the user explicitly asked for (and that are available) that haven't succeeded in this turn."""
    ok = {o.call.name for o in outcomes if o.status == "ok"}
    tried = {o.call.name for o in outcomes}
    return [tool for pattern, tool in _REQUESTS
            if pattern.search(user_text) and tool in offered and tool not in ok and tool not in tried]


def unbacked_claim(text: str, outcomes: list[Outcome], prior: list[dict] | None = None) -> bool:
    """True if the text claims an action that no successful tool call performed.

    Backing comes from this turn's successful calls of the matching kind, or from an earlier turn's successful
    call on the same item (matched by the quoted title in its summary), e.g. recapping "groceries was deleted".
    """
    ok = [o.call.name for o in outcomes if o.status == "ok"]
    for m in CLAIMED_ACTION.finditer(text):
        start = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start())) + 1
        end = min([i for i in (text.find(".", m.end()), text.find("\n", m.end())) if i >= 0] or [len(text)])
        sentence = text[start:end].lower()
        for verbs, prefixes in _CLAIM_KINDS:
            if not verbs.search(m.group(0)):
                continue
            if any(name.startswith(prefixes) for name in ok):
                continue
            earlier = any(
                s.get("tool", "").startswith(prefixes)
                and any(t.lower() in sentence for t in _QUOTED.findall(s.get("summary") or ""))
                for s in (prior or [])
            )
            if not earlier:
                return True
    return False


async def model_node(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    ctx = runtime.context
    steps = state.get("steps", 0) + 1
    # On the last allowed step, offer no tools so the model must answer with what it has — and say so explicitly,
    # or it narrates actions it can no longer take ("Creating note…", seen live).
    tools = ctx.tools if steps < ctx.max_steps else None
    final_step = tools is None and bool(ctx.tools)
    prompt_msgs = state["messages"]
    if final_step:
        prompt_msgs = [*prompt_msgs, to_dict(ChatMessage("user", (
            "[System] You have used all tool steps for this request and cannot call tools now. Give the user your "
            "answer from what the tools returned, and say plainly which requested actions were NOT done.")))]
    text, calls, usage = [], [], None
    sentences: Counter[str] = Counter()
    pending_sentence = ""
    looping = False
    async for item in ctx.llm.stream([to_msg(m) for m in prompt_msgs], tools=tools):
        if looping:
            break  # closing the stream stops generation in Ollama too
        if isinstance(item, StreamStarted):
            if not ctx.started:
                ctx.started = True
                await ctx.emit(item)
            continue
        chunk: StreamChunk = item
        if chunk.tool_calls:
            calls += chunk.tool_calls
        if chunk.delta:
            delta = chunk.delta
            if not text and ctx.has_text:
                delta = delta.lstrip("\n")
                if not delta:
                    continue
                sep = "" if ctx.tail.endswith("\n\n") else ("\n" if ctx.tail.endswith("\n") else "\n\n")
                if sep:
                    await ctx.emit(StreamChunk(delta=sep))
            # Repetition guard: a small model can get stuck saying the same sentence forever (seen live: 72 s,
            # ~4k tokens of "I'll now list your open tasks."). A third identical sentence ends this step.
            pending_sentence += delta
            *done_sentences, pending_sentence = re.split(r"(?<=[.!?\n])", pending_sentence)
            for s in done_sentences:
                key = " ".join(s.lower().split())
                if len(key) >= 15:
                    sentences[key] += 1
                    looping = looping or sentences[key] >= 3
            if looping:
                log.warning("model repeated itself; stopping this step", extra={"sentence": max(sentences, key=sentences.get)[:120]})
                continue
            text.append(delta)
            ctx.has_text = True
            ctx.tail = (ctx.tail + delta)[-4:]
            await ctx.emit(StreamChunk(delta=delta))
        elif chunk.reasoning:
            await ctx.emit(chunk)
        if chunk.done:
            usage = chunk
    if usage:
        await ctx.emit(StreamChunk(done=True, prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens))
    said = "".join(text)
    msg = ChatMessage("assistant", said, tuple(calls))
    messages = [*state["messages"], to_dict(msg)]
    retry = False
    claimed = unbacked_claim(said, ctx.outcomes, ctx.prior_ok)
    if final_step and (claimed or PROMISED_ACTION.search(said[-300:])):
        # Can't retry (no steps left): never let a false claim stand.
        note = ("\n\n(Correction: I ran out of steps for this request, so anything above that I said I'd do or "
                "had done after the last tool result was NOT actually done. Ask me to finish it.)")
        await ctx.emit(StreamChunk(delta=note))
        log.warning("unbacked claim on the final step", extra={"text": said[-200:]})
    # Only a promise at the end of the reply counts ("…let me know" or a plan followed by an answer is fine).
    promised = PROMISED_ACTION.search(said[-300:])
    missing = unfulfilled_requests(ctx.user_request, ctx.outcomes, {t["function"]["name"] for t in ctx.tools})
    if not calls and tools and not final_step:
        problems = []
        if missing and not ctx.requests_checked:
            ctx.requests_checked = True
            problems.append(f"The user asked for {', '.join(missing)} and you haven't called "
                            f"{'it' if len(missing) == 1 else 'them'}.")
        if (claimed or promised) and not ctx.nudged:
            ctx.nudged = True
            problems.append(("Your message claimed an action" if claimed else "Your message said you would do "
                             "something") + " without calling a tool, so it was NOT done.")
        if problems:
            retry = True
            log.warning("agent turn incomplete; sending the model back",
                        extra={"missing": missing, "claimed": bool(claimed), "promised": bool(promised)})
            if claimed:
                note = "\n\n(Correction: I hadn't actually done that yet. Doing it now.)\n\n"
                await ctx.emit(StreamChunk(delta=note))
                ctx.tail = note[-4:]
            messages.append(to_dict(ChatMessage("user", "[System check] " + " ".join(problems) + (
                " Call the tool(s) now" + (f" — {', '.join(missing)} — " if missing else " ")
                + "using what you found above. If you can't, say plainly that it wasn't done."))))
        elif claimed:
            # Out of retries and still claiming something that didn't happen: never let it stand.
            undone = ", ".join(missing) if missing else "that last action"
            note = f"\n\n(Correction: {undone} was NOT actually done. Ask me again and I'll do it.)"
            await ctx.emit(StreamChunk(delta=note))
            log.warning("unbacked claim after retry; correction shown", extra={"missing": missing})
    return {"messages": messages, "steps": steps, "retry": retry,
            "pending": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in calls]}


async def approve_node(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    ctx = runtime.context
    decisions = dict(state.get("decisions") or {})
    rejected = dict(state.get("rejected") or {})
    for c in state.get("pending") or []:
        if c["id"] in decisions or c["id"] in rejected:
            continue
        p = prepare(ToolCall(**c), ctx.prefs)
        if p.mode != "confirm":
            continue
        action = describe(p)
        if p.tool and p.tool.precheck and p.args is not None:
            try:  # read-only, so safe to repeat when this node re-runs on resume
                action = await p.tool.precheck(ctx.tool_ctx, p.args)
            except ToolError as e:
                rejected[c["id"]] = str(e)  # don't ask the user to approve something impossible
                continue
        # Pauses the whole graph; the turn asks the user and resumes with True/False.
        decisions[c["id"]] = bool(interrupt({
            "approval_id": c["id"], "tool": c["name"], "args": p.args.model_dump(exclude_none=True) if p.args else {},
            "description": p.tool.description if p.tool else "", "call": action,
            "always_confirm": bool(p.tool and p.tool.always_confirm),
        }))
    return {"decisions": decisions, "rejected": rejected}


async def tools_node(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    ctx = runtime.context
    decisions = state.get("decisions") or {}
    results = []
    await ctx.send({"type": "state", "state": "executing"})
    rejected = state.get("rejected") or {}
    for c in state.get("pending") or []:
        call = ToolCall(**c)
        p = prepare(call, ctx.prefs)
        if call.id in rejected:
            p = Prepared(call, p.tool, p.args, "invalid", f"Tool error: {rejected[call.id]}")
        await ctx.send({"type": "tool_call", "id": call.id, "tool": call.name, "args": call.arguments})
        out = await execute(p, ctx.tool_ctx, approved=decisions.get(call.id))
        ctx.outcomes.append(out)
        await ctx.send({"type": "tool_result", **out.step()})
        results.append(to_dict(ChatMessage("tool", out.content, tool_name=call.name, tool_call_id=call.id)))
    return {"messages": [*state["messages"], *results], "pending": []}


def _route(state: AgentState) -> str:
    if state.get("pending"):
        return "approve"
    return "model" if state.get("retry") else END


def build_graph():
    g = StateGraph(AgentState, context_schema=AgentContext)
    g.add_node("model", model_node)
    g.add_node("approve", approve_node)
    g.add_node("tools", tools_node)
    g.add_edge(START, "model")
    g.add_conditional_edges("model", _route, {"approve": "approve", "model": "model", END: END})
    g.add_edge("approve", "tools")
    g.add_edge("tools", "model")
    return g.compile(checkpointer=InMemorySaver())


GRAPH = build_graph()


class Approvals:
    """Per-connection registry of approval requests waiting for the user."""

    def __init__(self) -> None:
        self._waiting: dict[str, asyncio.Future[bool]] = {}

    def wait(self, approval_id: str) -> asyncio.Future[bool]:
        fut = asyncio.get_running_loop().create_future()
        self._waiting[approval_id] = fut
        return fut

    def resolve(self, approval_id: str, approved: bool) -> bool:
        fut = self._waiting.pop(approval_id, None)
        if fut is None or fut.done():
            return False
        fut.set_result(approved)
        return True

    def cancel_all(self) -> None:
        for fut in self._waiting.values():
            if not fut.done():
                fut.cancel()
        self._waiting.clear()
