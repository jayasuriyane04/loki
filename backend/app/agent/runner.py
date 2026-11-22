"""Runs the agent graph for one turn and exposes it as the same stream the chat service already consumes."""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langgraph.types import Command

from app.agent.graph import GRAPH, AgentContext, Approvals, to_dict
from app.llm.base import ChatMessage, StreamChunk
from app.llm.router import StreamStarted

log = logging.getLogger(__name__)
_DONE = object()


async def run_agent(
    messages: list[ChatMessage], ctx: AgentContext, approvals: Approvals, *, approval_timeout_s: float
) -> AsyncIterator[StreamStarted | StreamChunk]:
    """Yield the reply as it streams. Tool calls/results and approval requests go to the client via ctx.send."""
    queue: asyncio.Queue[Any] = asyncio.Queue()

    async def emit(item: Any) -> None:
        await queue.put(item)

    ctx.emit = emit
    config = {"configurable": {"thread_id": f"turn-{uuid.uuid4()}"}}

    async def drive() -> None:
        try:
            payload: Any = {"messages": [to_dict(m) for m in messages], "steps": 0}
            while True:
                interrupted = None
                async for update in GRAPH.astream(payload, config, context=ctx, stream_mode="updates"):
                    if "__interrupt__" in update:
                        interrupted = update["__interrupt__"][0].value
                if interrupted is None:
                    break
                approval_id = interrupted["approval_id"]
                await ctx.send({"type": "approval_required", **interrupted})
                try:
                    approved = await asyncio.wait_for(approvals.wait(approval_id), timeout=approval_timeout_s)
                except TimeoutError:
                    approved = False
                    log.info("approval timed out", extra={"tool": interrupted["tool"]})
                await ctx.send({"type": "approval_resolved", "approval_id": approval_id, "approved": approved})
                payload = Command(resume=approved)
            await queue.put(_DONE)
        except BaseException as e:  # surface errors (incl. LLMError) to the consumer
            await queue.put(e)
        finally:
            try:
                await GRAPH.checkpointer.adelete_thread(config["configurable"]["thread_id"])
            except Exception:  # noqa: BLE001
                pass

    task = asyncio.create_task(drive())
    try:
        while True:
            item = await queue.get()
            if item is _DONE:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
