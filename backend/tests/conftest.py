import asyncio
import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

# Isolated database + settings before the app is imported.
# Default: a throwaway SQLite file. Set TEST_DATABASE_URL (a Postgres database used only for tests) to run the
# same suite on Postgres + pgvector; its schema is wiped at the start of every run.
_test_db = os.environ.get("TEST_DATABASE_URL")
if _test_db:
    if not _test_db.rsplit("/", 1)[-1].endswith("_test"):
        raise RuntimeError("TEST_DATABASE_URL must name a database ending in _test (its contents are wiped)")

    async def _reset_postgres(url: str) -> None:
        import asyncpg

        con = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
        try:
            await con.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        finally:
            await con.close()

    asyncio.run(_reset_postgres(_test_db))
    os.environ["DATABASE_URL"] = _test_db
else:
    _tmp = Path(tempfile.mkdtemp(prefix="loki-test-"))
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["ENVIRONMENT"] = "test"
os.environ["LLM_FALLBACK_PROVIDER"] = ""
os.environ["LLM_FALLBACK_MODEL"] = ""
os.environ["LLM_WARMUP"] = "false"
os.environ["RERANK_MODEL_DIR"] = ""  # tests use FakeReranker; the real ONNX model is exercised by the live check
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="loki-uploads-")
os.environ["VOICE_ENABLED"] = "false"  # real Whisper/Kokoro are exercised by the live check, not unit tests

from fastapi.testclient import TestClient  # noqa: E402

from app.core import ratelimit  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.knowledge.rerank import Reranker  # noqa: E402
from app.knowledge.service import KnowledgeService  # noqa: E402
from app.llm.embeddings import EmbeddingProvider  # noqa: E402
from app.memory.service import MemoryService  # noqa: E402
from app.llm.base import ChatMessage, LLMError, LLMProvider, ProviderHealth, StreamChunk, ToolCall  # noqa: E402
from app.llm.router import LLMRouter  # noqa: E402
from app.main import app  # noqa: E402


class FakeProvider(LLMProvider):
    """Deterministic provider for tests. Records the context it was called with."""

    name = "fake"

    def __init__(self, model: str = "fake-1", *, reply: str = "Hello from LOKI.", fail: bool = False, delay: float = 0):
        super().__init__(model)
        self.reply = reply
        self.fail = fail
        self.delay = delay
        self.calls: list[list[ChatMessage]] = []
        self.completions: list[tuple[list[ChatMessage], dict | None]] = []
        self.extraction_ops: list[list[dict]] = []  # one list of operations per extraction call
        # Agent tests: one entry per model step. A list of (name, args) = call those tools; a str = reply text.
        self.script: list[list[tuple[str, dict]] | str] = []
        self.tools_offered: list[list[str] | None] = []

    async def stream_chat(self, messages, *, temperature, max_tokens, tools=None) -> AsyncIterator[StreamChunk]:
        self.calls.append(messages)
        self.tools_offered.append([t["function"]["name"] for t in tools] if tools else None)
        if self.fail:
            raise LLMError("fake provider down", provider=self.name)
        if self.script:
            step = self.script.pop(0)
            if isinstance(step, list):
                yield StreamChunk(tool_calls=[ToolCall(f"call_{i}_{len(self.calls)}", n, a) for i, (n, a) in enumerate(step)])
                yield StreamChunk(done=True, prompt_tokens=5, completion_tokens=5)
                return
            reply = step
        else:
            reply = self.reply
        for word in reply.split(" "):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield StreamChunk(delta=word + " ")
        yield StreamChunk(done=True, prompt_tokens=11, completion_tokens=len(reply.split(" ")))

    async def complete(self, messages, *, temperature, max_tokens, json_schema=None) -> str:
        self.completions.append((messages, json_schema))
        if self.fail:
            raise LLMError("fake provider down", provider=self.name)
        if json_schema is not None:  # memory extraction
            return json.dumps({"operations": self.extraction_ops.pop(0) if self.extraction_ops else []})
        return "- Summary of the earlier conversation."

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.name, self.model, not self.fail, 1, "down" if self.fail else None)


class FakeEmbeddings(EmbeddingProvider):
    """Deterministic bag-of-words hashing: texts sharing words are similar, unrelated texts are not."""

    name, model, dim = "fake", "fake-embed", 1024
    _STOP = {"the", "a", "an", "is", "are", "of", "to", "and", "my", "i", "what", "do", "you", "about", "me", "it", "for", "in", "on", "s"}

    def __init__(self, fail: bool = False):
        self.fail = fail

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for w in re.findall(r"[a-z0-9]+", text.lower()):
            if w not in self._STOP:
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    async def embed_documents(self, texts):
        if self.fail:
            raise LLMError("embeddings down", provider=self.name)
        return [self._vec(t) for t in texts]

    async def embed_query(self, text):
        if self.fail:
            raise LLMError("embeddings down", provider=self.name)
        return self._vec(text)

    async def health(self):
        return ProviderHealth(self.name, self.model, True, 1)


class FakeReranker(Reranker):
    """Relevance = share of the query's content words found in the passage."""

    name, state = "fake-rerank", "ready"

    async def load(self):
        pass

    async def score(self, query, passages):
        q = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in FakeEmbeddings._STOP and len(w) > 2}
        return [len(q & set(re.findall(r"[a-z0-9]+", p.lower()))) / (len(q) or 1) for p in passages]


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def client(fake: FakeProvider):
    ratelimit.login_limiter._events.clear()
    ratelimit.register_limiter._events.clear()
    with TestClient(app) as c:
        app.state.llm = LLMRouter(fake, None, temperature=0, max_tokens=64)
        app.state.embeddings = FakeEmbeddings()
        app.state.memory = MemoryService(app.state.llm, app.state.embeddings, get_settings())
        app.state.ingestor.embeddings = app.state.embeddings
        app.state.knowledge = KnowledgeService(app.state.embeddings, FakeReranker(), get_settings())
        app.state.scheduler.services.update(llm=app.state.llm, embeddings=app.state.embeddings, knowledge=app.state.knowledge)
        yield c


_counter = 0


@pytest.fixture
def user(client: TestClient) -> dict:
    global _counter
    _counter += 1
    body = {"email": f"tony{_counter}@example.com", "password": "correct-horse-battery", "display_name": "Tony"}
    r = client.post("/api/auth/register", json=body)
    assert r.status_code == 201, r.text
    return body
