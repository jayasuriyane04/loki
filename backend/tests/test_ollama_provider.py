import json

import httpx
import pytest

from app.llm.base import ChatMessage, LLMError
from app.llm.ollama import OllamaProvider


def _provider(handler, think: str = "auto") -> OllamaProvider:
    p = OllamaProvider("qwen3:4b", base_url="http://ollama", connect_timeout_s=1, idle_timeout_s=1, retries=0, think=think)
    p._client = httpx.AsyncClient(base_url="http://ollama", transport=httpx.MockTransport(handler))
    return p


def _ndjson(*objs) -> bytes:
    return "\n".join(json.dumps(o) for o in objs).encode()


async def test_reasoning_is_hidden_and_think_requested_for_thinking_models():
    sent = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion", "thinking"]})
        sent.update(json.loads(req.content))
        return httpx.Response(
            200,
            content=_ndjson(
                {"message": {"thinking": "secret plan"}, "done": False},
                {"message": {"content": "Hi "}, "done": False},
                {"message": {"content": "Tony."}, "done": True, "prompt_eval_count": 9, "eval_count": 4},
            ),
        )

    chunks = [c async for c in _provider(handler).stream_chat([ChatMessage("user", "hi")], temperature=0, max_tokens=10)]
    assert sent["think"] is True
    assert chunks[0].reasoning and chunks[0].delta == ""
    assert "".join(c.delta for c in chunks) == "Hi Tony."
    assert chunks[-1].done and chunks[-1].completion_tokens == 4


async def test_think_omitted_for_plain_models():
    sent = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"]})
        sent.update(json.loads(req.content))
        return httpx.Response(200, content=_ndjson({"message": {"content": "ok"}, "done": True}))

    [c async for c in _provider(handler).stream_chat([ChatMessage("user", "hi")], temperature=0, max_tokens=10)]
    assert "think" not in sent


async def test_http_error_becomes_llm_error():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/show":
            return httpx.Response(404, json={"error": "model not found"})
        return httpx.Response(404, json={"error": "model 'qwen3:4b' not found"})

    with pytest.raises(LLMError, match="HTTP 404"):
        [c async for c in _provider(handler).stream_chat([ChatMessage("user", "hi")], temperature=0, max_tokens=10)]
