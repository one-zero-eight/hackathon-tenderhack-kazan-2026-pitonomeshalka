import unittest

import redis

from backend.src.history import SearchHistoryStore


class FakePipeline:
    def __init__(self, fake):
        self._fake, self._ops = fake, []
    def lrem(self, key, count, value):
        self._ops.append(("lrem", key, count, value)); return self
    def lpush(self, key, value):
        self._ops.append(("lpush", key, value)); return self
    def ltrim(self, key, start, end):
        self._ops.append(("ltrim", key, start, end)); return self
    def expire(self, key, seconds):
        self._ops.append(("expire", key, seconds)); return self
    def execute(self):
        for name, *args in self._ops:
            getattr(self._fake, f"_{name}")(*args)
        return [True] * len(self._ops)


class FakeRedis:
    def __init__(self):
        self.data: dict[str, object] = {}
        self.ttls: dict[str, int] = {}
    def pipeline(self):
        return FakePipeline(self)
    def _lrem(self, key, count, value):
        items = self.data.get(key) or []
        if count == 0:
            self.data[key] = [x for x in items if x != value]
            return
        for _ in range(count):
            try:
                items.remove(value)  # list.remove drops the first occurrence, like LREM
            except ValueError:
                break
        self.data[key] = items
    def _lpush(self, key, value):
        self.data.setdefault(key, [])
        self.data[key] = [value, *self.data[key]]
    def _ltrim(self, key, start, end):
        self.data[key] = (self.data.get(key) or [])[start : end + 1]
    def _expire(self, key, seconds):
        self.ttls[key] = seconds
    def lrange(self, key, start, end):
        return (self.data.get(key) or [])[start : end + 1]
    def set(self, key, value, ex=None):
        self.data[key] = value
        if ex is not None:
            self.ttls[key] = ex
    def get(self, key):
        return self.data.get(key)


class FailingRedis(FakeRedis):
    """Redis outage: every direct read or write raises."""

    def set(self, key, value, ex=None):
        raise redis.RedisError("redis write failed")

    def lrange(self, key, start, end):
        raise redis.RedisError("redis read failed")

    def get(self, key):
        raise redis.RedisError("redis read failed")


class SearchHistoryStoreTests(unittest.TestCase):
    def make_store(self, client=None, **kwargs):
        store = SearchHistoryStore("", **kwargs)
        store._client = client if client is not None else FakeRedis()
        return store

    def result_keys(self, store):
        return [key for key in store._client.data if key.startswith("search_history_result:")]

    def test_add_without_result_stores_only_the_query(self):
        store = self.make_store()
        store.add("s1", "дрель")
        self.assertEqual(store.get("s1"), ["дрель"])
        self.assertIsNone(store.get_result("s1", "дрель"))

    def test_add_with_result_saves_query_and_result(self):
        store = self.make_store()
        store.add("s1", "дрель 18 В", {"run_id": "r1"})
        self.assertEqual(store.get_result("s1", "дрель 18 В"), {"run_id": "r1"})
        self.assertEqual(set(store._client.ttls.values()), {604800})

    def test_lookup_normalizes_query(self):
        store = self.make_store()
        store.add("s1", "  дрель 18 В  ", {"run_id": "r1"})
        self.assertEqual(store.get_result("s1", "дрель 18 В"), {"run_id": "r1"})
        long_query = "д" * 600
        store.add("s1", long_query, {"run_id": "r2"})
        self.assertEqual(store.get_result("s1", long_query[:500]), {"run_id": "r2"})

    def test_repeated_add_overwrites_result(self):
        store = self.make_store()
        store.add("s1", "дрель", {"run_id": "r1"})
        store.add("s1", "дрель", {"run_id": "r2"})
        self.assertEqual(store.get_result("s1", "дрель"), {"run_id": "r2"})
        self.assertEqual(len(self.result_keys(store)), 1)

    def test_oversized_result_is_skipped(self):
        store = self.make_store()
        store.add("s1", "дрель", {"blob": "x" * 600_000})
        self.assertEqual(store.get("s1"), ["дрель"])
        self.assertIsNone(store.get_result("s1", "дрель"))

    def test_unknown_query_returns_none(self):
        store = self.make_store()
        store.add("s1", "дрель", {"run_id": "r1"})
        self.assertIsNone(store.get_result("s1", "шуруповерт"))

    def test_corrupt_json_returns_none(self):
        store = self.make_store()
        store.add("s1", "дрель", {"run_id": "r1"})
        key, = self.result_keys(store)
        store._client.data[key] = "{broken"
        self.assertIsNone(store.get_result("s1", "дрель"))

    def test_redis_errors_are_swallowed(self):
        store = self.make_store(FailingRedis())
        store.add("s1", "дрель")
        store.add("s1", "дрель", {"run_id": "r1"})
        self.assertIsNone(store.get_result("s1", "дрель"))
        self.assertEqual(store.get("s1"), [])

    def test_invalid_session_id_is_ignored(self):
        store = self.make_store()
        store.add("bad id!", "дрель", {"run_id": "r1"})
        self.assertEqual(store._client.data, {})
        self.assertEqual(store.get("bad id!"), [])
        self.assertIsNone(store.get_result("bad id!", "дрель"))

    def test_disabled_store_noops(self):
        store = SearchHistoryStore("")
        store.add("s1", "дрель", {"run_id": "r1"})
        self.assertEqual(store.get("s1"), [])
        self.assertIsNone(store.get_result("s1", "дрель"))


if __name__ == "__main__":
    unittest.main()
