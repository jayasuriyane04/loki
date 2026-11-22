import math
import time
from abc import ABC, abstractmethod

import httpx

from app.core.config import Settings
from app.llm.base import LLMError, ProviderHealth

# qwen3-embedding is instruction-aware: queries (not stored documents) get a task description.
_QUERY_INSTRUCTIONS = {
    "qwen3-embedding": "Instruct: Given a message from the user, retrieve stored facts about the user, "
    "their preferences, projects and past events that help answer it\nQuery: ",
}


class EmbeddingProvider(ABC):
    name: str
    model: str
    dim: int

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]: ...

    @abstractmethod
    async def health(self) -> ProviderHealth: ...

    async def aclose(self) -> None:  # noqa: B027
        pass


def _normalise(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class OllamaEmbeddings(EmbeddingProvider):
    name = "ollama"

    def __init__(self, model: str, *, base_url: str, dim: int, timeout_s: float = 30) -> None:
        self.model = model
        self.dim = dim
        self._prefix = next((p for k, p in _QUERY_INSTRUCTIONS.items() if model.startswith(k)), "")
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s)

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = await self._client.post("/api/embed", json={"model": self.model, "input": texts})
        except httpx.HTTPError as e:
            raise LLMError(f"Embedding request failed ({type(e).__name__}).", provider=self.name) from e
        if resp.status_code != 200:
            raise LLMError(f"Embedding failed: HTTP {resp.status_code} {resp.text[:200]}", provider=self.name)
        vectors = resp.json().get("embeddings") or []
        if len(vectors) != len(texts) or any(len(v) != self.dim for v in vectors):
            got = len(vectors[0]) if vectors else 0
            raise LLMError(
                f"Embedding model {self.model} returned {got}-dim vectors; EMBEDDING_DIM is {self.dim}.",
                provider=self.name,
            )
        return [_normalise(v) for v in vectors]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts)

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([self._prefix + text]))[0]

    async def health(self) -> ProviderHealth:
        start = time.perf_counter()
        try:
            await self._embed(["health check"])
            return ProviderHealth(self.name, self.model, True, int((time.perf_counter() - start) * 1000))
        except LLMError as e:
            return ProviderHealth(self.name, self.model, False, None, str(e))

    async def aclose(self) -> None:
        await self._client.aclose()


def build_embeddings(s: Settings) -> EmbeddingProvider:
    return OllamaEmbeddings(s.embedding_model, base_url=s.ollama_base_url, dim=s.embedding_dim)
