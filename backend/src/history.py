"""Redis-backed search query history with TTL expiry."""

from __future__ import annotations

import logging
import re

import redis

logger = logging.getLogger("uvicorn.error")

_KEY_PREFIX = "search_history:"
_MAX_QUERY_LENGTH = 500


def _sanitize_session_id(session_id: str) -> str | None:
    """Accept only alphanumeric + hyphen/underscore session IDs."""
    if not session_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session_id):
        return None
    return session_id


class SearchHistoryStore:
    """Stores per-session search queries in Redis with automatic TTL cleanup."""

    def __init__(self, redis_url: str, *, max_items: int = 5, ttl_seconds: int = 604800):
        self._max_items = max_items
        self._ttl_seconds = ttl_seconds
        self._client: redis.Redis | None = None
        if redis_url:
            try:
                self._client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=3)
                self._client.ping()
                logger.info("Redis connected for search history")
            except redis.RedisError as error:
                logger.warning("Redis unavailable at startup, history disabled: %s", error)
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def add(self, session_id: str, query: str) -> None:
        """Prepend a query to the session's history, trimming to max_items."""
        if not self._client:
            return
        safe_id = _sanitize_session_id(session_id)
        if not safe_id:
            return
        text = query.strip()[:_MAX_QUERY_LENGTH]
        if not text:
            return
        key = f"{_KEY_PREFIX}{safe_id}"
        try:
            pipe = self._client.pipeline()
            # Remove duplicate if it already exists, then push to front
            pipe.lrem(key, 1, text)
            pipe.lpush(key, text)
            pipe.ltrim(key, 0, self._max_items - 1)
            pipe.expire(key, self._ttl_seconds)
            pipe.execute()
        except redis.RedisError as error:
            logger.warning("Failed to save search history: %s", error)

    def get(self, session_id: str) -> list[str]:
        """Return the most recent queries for a session, newest first."""
        if not self._client:
            return []
        safe_id = _sanitize_session_id(session_id)
        if not safe_id:
            return []
        key = f"{_KEY_PREFIX}{safe_id}"
        try:
            return self._client.lrange(key, 0, self._max_items - 1)
        except redis.RedisError as error:
            logger.warning("Failed to read search history: %s", error)
            return []

    def close(self) -> None:
        if self._client:
            try:
                self._client.close()
            except redis.RedisError:
                pass
