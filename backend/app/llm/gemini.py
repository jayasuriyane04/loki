import json
import time
import uuid
from collections.abc import AsyncIterator

import httpx

from app.llm.base import ChatMessage, LLMError, LLMProvider, ProviderHealth, StreamChunk, ToolCall
from app.llm.http import open_stream


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None,
        base_url: str,
        connect_timeout_s: float,
        idle_timeout_s: float,
        retries: int,
    ) -> None:
        super().__init__(model)
        self._api_key = api_key
        self._retries = retries
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(connect=connect_timeout_s, read=idle_timeout_s, write=10, pool=5),
            headers={"x-goog-api-key": api_key or ""},
        )

    @staticmethod
    def _to_payload(
        messages: list[ChatMessage], temperature: float, max_tokens: int, tools: list[dict] | None = None
    ) -> dict:
        """Map chat messages (incl. tool calls/results) to Gemini `contents`. Untested without an API key."""
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        contents = []
        for m in messages:
            if m.role == "system":
                continue
            if m.role == "tool":
                contents.append({"role": "user", "parts": [
                    {"functionResponse": {"name": m.tool_name or "tool", "response": {"content": m.content}}}]})
                continue
            parts: list[dict] = [{"text": m.content}] if m.content else []
            parts += [{"functionCall": {"name": c.name, "args": c.arguments}} for c in m.tool_calls]
            contents.append({"role": "model" if m.role == "assistant" else "user", "parts": parts or [{"text": ""}]})
        payload: dict = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            payload["tools"] = [{"functionDeclarations": [
                {"name": t["function"]["name"], "description": t["function"]["description"],
                 "parametersJsonSchema": t["function"]["parameters"]} for t in tools]}]
        return payload

    async def stream_chat(
        self, messages: list[ChatMessage], *, temperature: float, max_tokens: int, tools: list[dict] | None = None
    ) -> AsyncIterator[StreamChunk]:
        if not self._api_key:
            raise LLMError("GEMINI_API_KEY is not set.", provider=self.name)
        payload = self._to_payload(messages, temperature, max_tokens, tools)
        usage: dict = {}
        async with open_stream(
            self._client,
            "POST",
            f"/models/{self.model}:streamGenerateContent",
            params={"alt": "sse"},
            json=payload,
            provider=self.name,
            retries=self._retries,
        ) as resp:
            try:
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = json.loads(line[5:].strip())
                    usage = data.get("usageMetadata") or usage
                    for cand in data.get("candidates", [])[:1]:
                        for part in (cand.get("content") or {}).get("parts", []):
                            if part.get("thought"):
                                continue
                            if fc := part.get("functionCall"):
                                yield StreamChunk(tool_calls=[ToolCall(
                                    id=f"call_{uuid.uuid4().hex[:10]}", name=fc.get("name", ""), arguments=fc.get("args") or {})])
                            elif text := part.get("text"):
                                yield StreamChunk(delta=text)
            except httpx.ReadTimeout as e:
                raise LLMError("Gemini stopped responding (idle timeout).", provider=self.name) from e
            except httpx.HTTPError as e:
                raise LLMError(f"Gemini stream failed: {type(e).__name__}", provider=self.name) from e
        yield StreamChunk(
            done=True,
            prompt_tokens=usage.get("promptTokenCount"),
            completion_tokens=usage.get("candidatesTokenCount"),
        )

    async def complete(
        self, messages: list[ChatMessage], *, temperature: float, max_tokens: int, json_schema: dict | None = None
    ) -> str:
        if not self._api_key:
            raise LLMError("GEMINI_API_KEY is not set.", provider=self.name)
        payload = self._to_payload(messages, temperature, max_tokens)
        if json_schema is not None:
            payload["generationConfig"]["responseMimeType"] = "application/json"
            payload["generationConfig"]["responseJsonSchema"] = json_schema
        try:
            resp = await self._client.post(f"/models/{self.model}:generateContent", json=payload, timeout=120)
        except httpx.HTTPError as e:
            raise LLMError(f"Gemini request failed ({type(e).__name__}).", provider=self.name) from e
        if resp.status_code != 200:
            raise LLMError(f"Gemini returned HTTP {resp.status_code}: {resp.text[:200]}", provider=self.name)
        parts = ((resp.json().get("candidates") or [{}])[0].get("content") or {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))

    async def health(self) -> ProviderHealth:
        if not self._api_key:
            return ProviderHealth(self.name, self.model, False, None, "GEMINI_API_KEY is not set")
        start = time.perf_counter()
        try:
            resp = await self._client.get(f"/models/{self.model}", timeout=8)
            latency = int((time.perf_counter() - start) * 1000)
            if resp.status_code != 200:
                return ProviderHealth(self.name, self.model, False, latency, f"HTTP {resp.status_code}")
            return ProviderHealth(self.name, self.model, True, latency)
        except httpx.HTTPError as e:
            return ProviderHealth(self.name, self.model, False, None, f"Gemini unreachable ({type(e).__name__})")

    async def aclose(self) -> None:
        await self._client.aclose()
