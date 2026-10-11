import tempfile
import unittest
from pathlib import Path

import redis
from fastapi.testclient import TestClient

from backend.src.app import create_app
from backend.src.history import SearchHistoryStore
from backend.src.schemas import AnalysisResponse
from backend.src.settings import Settings
from backend.tests.memory_store import MemoryStore


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

    def test_non_serializable_result_keeps_query_without_result(self):
        store = self.make_store()
        store.add("s1", "дрель", {"x": object()})
        self.assertEqual(store.get("s1"), ["дрель"])
        self.assertEqual(self.result_keys(store), [])

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


class FakeModel:
    """Classifier double whose health probe reports the configured model."""

    def __init__(self, model_name):
        self.model_name = model_name

    def factory(self, base_url, timeout):
        return self

    def health(self):
        return dict(model=self.model_name)


class FakeEmbedder:
    """Embedder double whose health probe echoes the configured model ID."""

    def __init__(self):
        self.model_id = None

    def factory(self, base_url, model_id, timeout):
        self.model_id = model_id
        return self

    def health(self):
        return dict(id=self.model_id, type="dense", dimensions=3)


class FakeStorage(MemoryStore):
    """MemoryStore plus the active-import lookup performed at app startup."""

    def get_active_import(self, key):
        return "fixture-import"


class HistoryRouteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = Settings(classifier_batch_size=0,
                                 results_dir=Path(self.directory.name) / "runs",
                                 startup_log_path=Path(self.directory.name) / "startup.jsonl",
                                 embedding_cache_path=Path(self.directory.name) / "embeddings.json",
                                 redis_url="")
        self.app = create_app(self.settings, client_factory=FakeModel(self.settings.classifier_model).factory,
                              embedding_client_factory=FakeEmbedder().factory,
                              store_factory=lambda _: FakeStorage())
        self.client = self.enterContext(TestClient(self.app))
        self.store = SearchHistoryStore("")
        self.store._client = FakeRedis()
        self.app.state.history = self.store
        self.result = AnalysisResponse(run_id="r1", status="ready_for_review", complete_inference=True,
                                       recommended_candidate=None, requires_review=True, properties=[],
                                       candidates=[], clarifying_question=None, warnings=[]).model_dump(mode="json")

    def test_post_history_with_result_then_get_it_back(self):
        response = self.client.post("/history", json={"session_id": "s1", "query": "дрель", "result": self.result})
        self.assertEqual(response.status_code, 200, response.text)
        cached = self.client.get("/history/s1/result", params={"query": "дрель"})
        self.assertEqual(cached.status_code, 200, cached.text)
        self.assertEqual(cached.json()["run_id"], "r1")

    def test_get_result_without_saved_result_returns_404(self):
        response = self.client.post("/history", json={"session_id": "s1", "query": "дрель"})
        self.assertEqual(response.status_code, 200, response.text)
        cached = self.client.get("/history/s1/result", params={"query": "дрель"})
        self.assertEqual(cached.status_code, 404)
        self.assertEqual(cached.json()["detail"], {"error": "No cached result for this query"})

    def test_get_result_unknown_query_returns_404(self):
        response = self.client.post("/history", json={"session_id": "s1", "query": "дрель", "result": self.result})
        self.assertEqual(response.status_code, 200, response.text)
        cached = self.client.get("/history/s1/result", params={"query": "шуруповерт"})
        self.assertEqual(cached.status_code, 404)
        self.assertEqual(cached.json()["detail"], {"error": "No cached result for this query"})

    def test_post_history_still_accepts_query_only(self):
        response = self.client.post("/history", json={"session_id": "s1", "query": "дрель"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get("/history/s1").json(), {"queries": ["дрель"]})


if __name__ == "__main__":
    unittest.main()
