import asyncio
import time
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Self

import httpx

try:
    _VERSION = version("silo")
except PackageNotFoundError:
    _VERSION = "dev"

USER_AGENT = f"Silo/{_VERSION}"


class ThrottledClient:
    """HTTP client with a minimum interval between requests."""

    def __init__(
        self,
        headers: dict[str, str] | None = None,
        request_interval_ms: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._interval = (request_interval_ms or 0) / 1000
        self._last_request = 0.0
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": USER_AGENT, **(headers or {})},
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def _throttle(self) -> None:
        if self._interval > 0:
            wait = self._last_request + self._interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
        self._last_request = time.monotonic()

    async def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        await self._throttle()
        resp = await self._client.get(url, **kwargs)
        resp.raise_for_status()
        return resp

    async def _post(self, url: str, **kwargs: Any) -> httpx.Response:
        await self._throttle()
        resp = await self._client.post(url, **kwargs)
        resp.raise_for_status()
        return resp
