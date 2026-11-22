from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str
    tool_calls: tuple[ToolCall, ...] = ()  # assistant messages that requested tools
    tool_name: str | None = None  # tool result messages
    tool_call_id: str | None = None


@dataclass
class StreamChunk:
    delta: str = ""
    reasoning: bool = False  # model is producing hidden reasoning; delta is empty
    tool_calls: list[ToolCall] | None = None  # the model asked to call tools
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
        self, messages: list[ChatMessage], *, temperature: float, max_tokens: int, tools: list[dict] | None = None
    ) -> AsyncIterator[StreamChunk]:
        """Yield text deltas (and tool calls, if `tools` were offered); the final chunk has done=True and token
        usage if the provider reports it."""

    @abstractmethod
    async def complete(
        self, messages: list[ChatMessage], *, temperature: float, max_tokens: int, json_schema: dict | None = None
    ) -> str:
        """Non-streaming completion. With `json_schema`, the reply is constrained to JSON matching it."""

    @abstractmethod
    async def health(self) -> ProviderHealth: ...

    async def warmup(self) -> None:  # noqa: B027 - optional hook
        """Load the model ahead of the first request (local providers)."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        pass
