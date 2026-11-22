import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

# Isolated database + settings before the app is imported.
_tmp = Path(tempfile.mkdtemp(prefix="loki-test-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["ENVIRONMENT"] = "test"
os.environ["LLM_FALLBACK_PROVIDER"] = ""
os.environ["LLM_FALLBACK_MODEL"] = ""
os.environ["LLM_WARMUP"] = "false"
os.environ["VOICE_ENABLED"] = "false"  # real Whisper/Kokoro are exercised by the live check, not unit tests

from fastapi.testclient import TestClient  # noqa: E402

from app.core import ratelimit  # noqa: E402
from app.llm.base import ChatMessage, LLMError, LLMProvider, ProviderHealth, StreamChunk  # noqa: E402
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

    async def stream_chat(self, messages, *, temperature, max_tokens) -> AsyncIterator[StreamChunk]:
        self.calls.append(messages)
        if self.fail:
            raise LLMError("fake provider down", provider=self.name)
        for word in self.reply.split(" "):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield StreamChunk(delta=word + " ")
        yield StreamChunk(done=True, prompt_tokens=11, completion_tokens=len(self.reply.split(" ")))

    async def health(self) -> ProviderHealth:
        return ProviderHealth(self.name, self.model, not self.fail, 1, "down" if self.fail else None)


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def client(fake: FakeProvider):
    ratelimit.login_limiter._events.clear()
    ratelimit.register_limiter._events.clear()
    with TestClient(app) as c:
        app.state.llm = LLMRouter(fake, None, temperature=0, max_tokens=64)
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
