"""Pub/sub for SSE (check-ins, board changes). Redis when available, in-process otherwise."""
import asyncio
import contextlib
import json
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

from app.core.config import get_settings

log = logging.getLogger(__name__)
_local: dict[str, set[asyncio.Queue]] = defaultdict(set)
_redis = None
_redis_checked = False


async def get_redis():
    global _redis, _redis_checked
    if _redis_checked:
        return _redis
    _redis_checked = True
    url = get_settings().redis_url
    if not url:
        return None
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(url, decode_responses=True)
        await asyncio.wait_for(r.ping(), 1.5)
        _redis = r
    except Exception as e:  # noqa: BLE001
        log.warning("Redis unavailable (%s); using in-process pub/sub and cache", e)
    return _redis


async def publish(channel: str, event: dict[str, Any]) -> None:
    r = await get_redis()
    if r:
        await r.publish(channel, json.dumps(event))
    for q in list(_local[channel]):
        q.put_nowait(event)


async def subscribe(channel: str) -> AsyncIterator[dict[str, Any]]:
    q: asyncio.Queue = asyncio.Queue()
    r = await get_redis()
    if r:
        ps = r.pubsub()
        await ps.subscribe(channel)
        try:
            while True:
                m = await ps.get_message(ignore_subscribe_messages=True, timeout=15)
                yield json.loads(m["data"]) if m else {"type": "ping"}
        finally:
            with contextlib.suppress(Exception):
                await ps.close()
    else:
        _local[channel].add(q)
        try:
            while True:
                try:
                    yield await asyncio.wait_for(q.get(), 15)
                except TimeoutError:
                    yield {"type": "ping"}
        finally:
            _local[channel].discard(q)


_cache: dict[str, str] = {}


async def cache_set(key: str, value: Any) -> None:
    s = json.dumps(value)
    r = await get_redis()
    if r:
        await r.set(key, s)
    _cache[key] = s


async def cache_get(key: str) -> Any | None:
    r = await get_redis()
    s = await r.get(key) if r else _cache.get(key)
    return json.loads(s) if s else None
