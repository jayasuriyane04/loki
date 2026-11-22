import json
import logging
import time
from collections.abc import AsyncIterator

import httpx

from app.llm.base import ChatMessage, LLMError, LLMProvider, ProviderHealth, StreamChunk
from app.llm.http import open_stream

log = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self,
        model: str,
        *,
        base_url: str,
        connect_timeout_s: float,
        idle_timeout_s: float,
        retries: int,
        think: str = "auto",
    ) -> None:
        super().__init__(model)
        self._retries = retries
        self._think_mode = think
        self._capabilities: set[str] | None = None
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(connect=connect_timeout_s, read=idle_timeout_s, write=10, pool=5),
        )

    async def _think_param(self) -> bool | None:
        if self._think_mode != "auto":
            return self._think_mode == "true"
        if self._capabilities is None:
            try:
                resp = await self._client.post("/api/show", json={"model": self.model}, timeout=5)
                resp.raise_for_status()
                self._capabilities = set(resp.json().get("capabilities") or [])
            except (httpx.HTTPError, ValueError):
                return None  # unknown; let the chat call surface any real error
        return True if "thinking" in self._capabilities else None

    async def stream_chat(
        self, messages: list[ChatMessage], *, temperature: float, max_tokens: int
    ) -> AsyncIterator[StreamChunk]:
        body: dict = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        think = await self._think_param()
        if think is not None:
            body["think"] = think
        async with open_stream(
            self._client, "POST", "/api/chat", json=body, provider=self.name, retries=self._retries
        ) as resp:
            try:
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise LLMError(f"Ollama error: {data['error']}", provider=self.name)
                    message = data.get("message") or {}
                    delta = message.get("content", "")
                    if message.get("thinking") and not delta:
                        yield StreamChunk(reasoning=True)
                        continue
                    if data.get("done"):
                        yield StreamChunk(
                            delta=delta,
                            done=True,
                            prompt_tokens=data.get("prompt_eval_count"),
                            completion_tokens=data.get("eval_count"),
                        )
                        return
                    if delta:
                        yield StreamChunk(delta=delta)
            except httpx.ReadTimeout as e:
                raise LLMError("Ollama stopped responding (idle timeout).", provider=self.name) from e
            except httpx.HTTPError as e:
                raise LLMError(f"Ollama stream failed: {type(e).__name__}", provider=self.name) from e
        raise LLMError("Ollama stream ended unexpectedly.", provider=self.name)

    async def warmup(self) -> None:
        """Ask Ollama to load the model into memory now, so the first real question doesn't pay for it."""
        start = time.perf_counter()
        try:
            resp = await self._client.post("/api/generate", json={"model": self.model}, timeout=180)
            resp.raise_for_status()
            log.info("llm warm", extra={"model": self.model, "s": round(time.perf_counter() - start, 1)})
        except httpx.HTTPError as e:
            log.warning("llm warm-up failed", extra={"model": self.model, "error": type(e).__name__})

    async def health(self) -> ProviderHealth:
        start = time.perf_counter()
        try:
            resp = await self._client.get("/api/tags", timeout=5)
            resp.raise_for_status()
            names = {m.get("name") for m in resp.json().get("models", [])}
            latency = int((time.perf_counter() - start) * 1000)
            wanted = self.model if ":" in self.model else f"{self.model}:latest"
            if wanted not in names:
                return ProviderHealth(
                    self.name, self.model, False, latency, f"Model not pulled. Run: ollama pull {self.model}"
                )
            return ProviderHealth(self.name, self.model, True, latency)
        except httpx.HTTPError as e:
            return ProviderHealth(
                self.name, self.model, False, None,
                f"Ollama unreachable at {self._client.base_url} ({type(e).__name__}). Is scripts/start-ollama.ps1 running?",
            )

    async def aclose(self) -> None:
        await self._client.aclose()
