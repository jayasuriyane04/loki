import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.core.config import ProviderName, Settings
from app.llm.base import ChatMessage, LLMError, LLMProvider, ProviderHealth, StreamChunk
from app.llm.gemini import GeminiProvider
from app.llm.ollama import OllamaProvider

log = logging.getLogger(__name__)


@dataclass
class StreamStarted:
    provider: str
    model: str
    fell_back: bool


def build_provider(name: ProviderName, model: str, s: Settings) -> LLMProvider:
    common = {
        "connect_timeout_s": s.llm_connect_timeout_s,
        "idle_timeout_s": s.llm_idle_timeout_s,
        "retries": s.llm_connect_retries,
    }
    if name == "ollama":
        return OllamaProvider(model, base_url=s.ollama_base_url, think=s.ollama_think, **common)
    if name == "gemini":
        return GeminiProvider(model, api_key=s.gemini_api_key, base_url=s.gemini_base_url, **common)
    raise ValueError(f"Unknown provider: {name}")


class LLMRouter:
    """Primary → fallback. Falls back only if the primary fails before producing its first chunk."""

    def __init__(self, primary: LLMProvider, fallback: LLMProvider | None, *, temperature: float, max_tokens: int):
        self.primary = primary
        self.fallback = fallback
        self.temperature = temperature
        self.max_tokens = max_tokens

    @classmethod
    def from_settings(cls, s: Settings) -> "LLMRouter":
        primary = build_provider(s.llm_primary_provider, s.llm_primary_model, s)
        fallback = None
        if s.llm_fallback_provider and s.llm_fallback_model:
            fallback = build_provider(s.llm_fallback_provider, s.llm_fallback_model, s)
        return cls(primary, fallback, temperature=s.llm_temperature, max_tokens=s.llm_max_output_tokens)

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[StreamStarted | StreamChunk]:
        candidates = [self.primary] + ([self.fallback] if self.fallback else [])
        last_error: LLMError | None = None
        for i, provider in enumerate(candidates):
            gen = provider.stream_chat(messages, temperature=self.temperature, max_tokens=self.max_tokens)
            try:
                first = await anext(gen)
            except LLMError as e:
                last_error = e
                log.warning("llm provider failed before first token", extra={"provider": provider.name, "error": str(e)})
                await gen.aclose()
                continue
            except StopAsyncIteration:
                last_error = LLMError("Provider returned an empty stream.", provider=provider.name)
                continue
            yield StreamStarted(provider.name, provider.model, fell_back=i > 0)
            try:
                yield first
                async for chunk in gen:
                    yield chunk
            finally:
                await gen.aclose()
            return
        assert last_error is not None
        raise last_error

    async def complete(
        self, messages: list[ChatMessage], *, json_schema: dict | None = None, max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        """Background/utility completion (memory extraction, summaries) with the same fallback policy."""
        last_error: LLMError | None = None
        for provider in [self.primary] + ([self.fallback] if self.fallback else []):
            try:
                return await provider.complete(
                    messages, temperature=temperature, max_tokens=max_tokens, json_schema=json_schema
                )
            except LLMError as e:
                last_error = e
                log.warning("llm completion failed", extra={"provider": provider.name, "error": str(e)})
        assert last_error is not None
        raise last_error

    async def health(self) -> tuple[ProviderHealth, ProviderHealth | None]:
        primary = await self.primary.health()
        fallback = await self.fallback.health() if self.fallback else None
        return primary, fallback

    async def aclose(self) -> None:
        await self.primary.aclose()
        if self.fallback:
            await self.fallback.aclose()
