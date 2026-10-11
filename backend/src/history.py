"""Redis-backed search query history with TTL expiry."""

from __future__ import annotations

import hashlib
import json
import logging
import re

import redis

logger = logging.getLogger("uvicorn.error")

_KEY_PREFIX = "search_history:"
_KEY_RESULT_PREFIX = "search_history_result:"
_MAX_QUERY_LENGTH = 500
_MAX_RESULT_BYTES = 524288


def _sanitize_session_id(session_id: str) -> str | None:
    """Accept only alphanumeric + hyphen/underscore session IDs."""
    if not session_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session_id):
        return None
    return session_id


def _normalize_query(query: str) -> str:
    """Collapse a raw query to the canonical text used for keys and storage."""
    return query.strip()[:_MAX_QUERY_LENGTH]


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

    def add(self, session_id: str, query: str, result: dict | None = None) -> None:
        """Prepend a query to the session's history, trimming to max_items."""
        if not self._client:
            return
        safe_id = _sanitize_session_id(session_id)
        if not safe_id:
            return
        text = _normalize_query(query)
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
            if result is not None:
                payload = json.dumps(result, ensure_ascii=False)
                if len(payload.encode("utf-8")) <= _MAX_RESULT_BYTES:
                    result_key = (f"{_KEY_RESULT_PREFIX}{safe_id}:"
                                  f"{hashlib.sha256(text.encode()).hexdigest()[:32]}")
                    self._client.set(result_key, payload, ex=self._ttl_seconds)
        except redis.RedisError as error:
            logger.warning("Failed to save search history: %s", error)
        except (TypeError, ValueError) as error:
            logger.warning("Cached result is not JSON-serializable: %s", error)

    def get_result(self, session_id: str, query: str) -> dict | None:
        """Return the cached analysis result for a session's query, if any."""
        if not self._client:
            return None
        safe_id = _sanitize_session_id(session_id)
        if not safe_id:
            return None
        key = (f"{_KEY_RESULT_PREFIX}{safe_id}:"
               f"{hashlib.sha256(_normalize_query(query).encode()).hexdigest()[:32]}")
        try:
            payload = self._client.get(key)
        except redis.RedisError as error:
            logger.warning("Failed to read cached search result: %s", error)
            return None
        if payload is None:
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError as error:
            logger.warning("Failed to decode cached search result: %s", error)
            return None

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
