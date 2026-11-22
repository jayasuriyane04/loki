import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from app.llm.base import LLMError


@asynccontextmanager
async def open_stream(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    provider: str,
    retries: int,
    **kwargs: Any,
) -> AsyncIterator[httpx.Response]:
    """Open a streaming request, retrying only connection-level failures (nothing has been generated yet).

    Non-2xx responses become LLMError with a short, secret-free message.
    """
    attempt = 0
    while True:
        try:
            req = client.build_request(method, url, **kwargs)
            resp = await client.send(req, stream=True)
            break
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            if attempt >= retries:
                raise LLMError(f"Cannot reach {provider} ({type(e).__name__}).", provider=provider) from e
            attempt += 1
            await asyncio.sleep(0.5 * 2**attempt)
        except httpx.HTTPError as e:
            raise LLMError(f"{provider} request failed ({type(e).__name__}).", provider=provider) from e

    try:
        if resp.status_code >= 400:
            body = (await resp.aread()).decode(errors="replace")[:300]
            raise LLMError(f"{provider} returned HTTP {resp.status_code}: {body}", provider=provider)
        yield resp
    finally:
        await resp.aclose()
