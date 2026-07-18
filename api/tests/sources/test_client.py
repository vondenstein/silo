import time

import httpx

from silo.sources.client import ThrottledClient


async def test_throttle_enforces_minimum_interval():
    stamps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        stamps.append(time.monotonic())
        return httpx.Response(200, json={})

    async with ThrottledClient(
        request_interval_ms=80, transport=httpx.MockTransport(handler)
    ) as client:
        await client._get("http://x/1")
        await client._get("http://x/2")

    # A lower bound can't flake: asyncio.sleep never wakes early; the small
    # epsilon absorbs monotonic-clock float noise.
    assert stamps[1] - stamps[0] >= 0.075


async def test_default_headers_carry_user_agent():
    # CR-197: every ThrottledClient-derived adapter self-identifies; a caller
    # header can still override.
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"].startswith("Silo/")
        return httpx.Response(200, json={})

    async with ThrottledClient(transport=httpx.MockTransport(handler)) as client:
        await client._get("http://x/")
