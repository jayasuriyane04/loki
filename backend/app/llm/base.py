from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass
class StreamChunk:
    delta: str = ""
    reasoning: bool = False  # model is producing hidden reasoning; delta is empty
    done: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass
class ProviderHealth:
    provider: str
    model: str
    ok: bool
    latency_ms: int | None = None
    error: str | None = None


class LLMError(Exception):
    """Raised by providers. `message` is safe to show to users (never contains secrets)."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message)
        self.provider = provider


class LLMProvider(ABC):
    name: str

    def __init__(self, model: str) -> None:
        self.model = model

    @abstractmethod
    def stream_chat(
        self, messages: list[ChatMessage], *, temperature: float, max_tokens: int
    ) -> AsyncIterator[StreamChunk]:
        """Yield text deltas; the final chunk has done=True and token usage if the provider reports it."""

    @abstractmethod
    async def health(self) -> ProviderHealth: ...

    async def warmup(self) -> None:  # noqa: B027 - optional hook
        """Load the model ahead of the first request (local providers)."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        pass
