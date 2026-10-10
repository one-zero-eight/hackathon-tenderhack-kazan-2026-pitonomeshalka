"""Offline tests for meow-embed transport, cache and semantic retrieval."""

import base64
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import struct
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch
from urllib.error import URLError

import embedding_retrieval as er


def encoded_response(vectors):
    return {"texts_count": len(vectors), "dense": {
        "model_id": er.MODEL, "dtype": "float32", "encoding": "base64",
        "shape": [len(vectors), len(vectors[0])],
        "data": base64.b64encode(struct.pack(f"<{sum(map(len, vectors))}f",
                                             *(value for vector in vectors for value in vector))).decode(),
    }}


class ProtocolTests(unittest.TestCase):
    def test_health_checks_models_without_embedding(self):
        model = dict(id=er.MODEL, type="dense", dimensions=768, device="cuda")

        def serve(request, timeout):
            self.assertEqual(request.full_url, "http://example:8067/models")
            self.assertEqual(request.get_method(), "GET")
            self.assertIsNone(request.data)
            self.assertEqual(timeout, 2)
            return io.BytesIO(json.dumps({"models": [model]}).encode())

        with patch.object(er, "urlopen", side_effect=serve):
            self.assertEqual(er.MeowEmbedClient("http://example:8067/", timeout=2).health(), model)

    def test_health_rejects_missing_dense_model_and_invalid_response(self):
        for result in ({"models": []}, {"models": [{"id": er.MODEL, "type": "sparse"}]},
                       {"models": [{"id": "other", "type": "dense"}]}, {"models": None}, []):
            with self.subTest(result=result), patch.object(er, "urlopen", return_value=io.BytesIO(json.dumps(result).encode())):
                with self.assertRaises(er.EmbeddingError):
                    er.MeowEmbedClient().health()

    def test_health_connection_error_is_not_retried(self):
        with patch.object(er, "urlopen", side_effect=URLError("offline")) as transport:
            with self.assertRaisesRegex(er.EmbeddingError, "unavailable"):
                er.MeowEmbedClient().health()
            self.assertEqual(transport.call_count, 1)

    def test_http_payload_prompts_and_base64_float32_response(self):
        response = encoded_response([[3, 4], [0, 2]])

        def serve(request, timeout):
            self.assertEqual(request.full_url, "http://example:8067/embed")
            self.assertEqual(timeout, 7)
            self.assertEqual(json.loads(request.data), {
                "texts": ["Стул", "Табурет"], "dense_model_id": er.MODEL,
                "dense_prompt": er.DOCUMENT_PROMPT,
            })
            self.assertIn("Стул", request.data.decode())
            return io.BytesIO(json.dumps(response).encode())

        with patch.object(er, "urlopen", side_effect=serve):
            vectors = er.MeowEmbedClient("http://example:8067/", timeout=7).embed(
                ["Стул", "Табурет"], er.DOCUMENT_PROMPT)
        self.assertEqual(vectors, [[.6, .8], [0, 1]])

    def test_invalid_model_shape_bytes_and_vectors_are_rejected(self):
        valid = encoded_response([[1, 0]])
        cases = []
        for field, value in (("model_id", "other"), ("shape", [2, 2]), ("data", "AA=="),
                             ("dtype", "float64"), ("data", "!not-base64!")):
            result = deepcopy(valid)
            result["dense"][field] = value
            cases.append(result)
        cases.extend([encoded_response([[float("nan"), 1]]), encoded_response([[0, 0]]),
                      {"texts_count": 1, "dense": None}])
        for result in cases:
            with self.subTest(result=result), patch.object(er, "urlopen", return_value=io.BytesIO(json.dumps(result).encode())):
                with self.assertRaises(er.EmbeddingError):
                    er.MeowEmbedClient().embed(["Стул"], er.DOCUMENT_PROMPT)

    def test_unavailable_service_is_not_retried(self):
        with patch.object(er, "urlopen", side_effect=URLError("offline")) as transport:
            with self.assertRaisesRegex(er.EmbeddingError, "unavailable"):
                er.MeowEmbedClient().embed(["Табуретка"], er.QUERY_PROMPT)
            self.assertEqual(transport.call_count, 1)


class FakeClient:
    model_id = er.MODEL

    def __init__(self):
        self.calls = []
        self.fail = False

    def embed(self, texts, prompt):
        self.calls.append((list(texts), prompt))
        if self.fail:
            raise er.EmbeddingError("offline")
        # Controlled geometry tests retrieval behavior, not real-model quality.
        return [[0, 2] if any(word in text.lower() for word in ("стул", "табур"))
                else [2, 0] for text in texts]


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = Path(self.directory.name) / "cache.json"
        self.client = FakeClient()
        self.catalog = {"positions": [
            {"key": "chair@1", "code": "chair", "version": "1", "name": "Стул", "domains": ["furniture"]},
            {"key": "chair@2", "code": "chair", "version": "2", "name": "Стул", "domains": ["furniture"]},
            {"key": "drill@1", "code": "drill", "version": "1", "name": "Дрель", "domains": ["tools"]},
        ]}

    def retriever(self, client=None):
        return er.EmbeddingRetriever(self.catalog, client or self.client, self.cache, batch_size=1)

    def test_zero_word_overlap_scope_versions_and_full_query(self):
        query = "Табуретка для кухни без спинки"
        result = self.retriever().retrieve(self.catalog, query, top_k=3)
        self.assertEqual(result["positions"][0]["key"], "chair@1")
        self.assertEqual({p["key"] for p in result["positions"]}, {"chair@1", "chair@2", "drill@1"})
        self.assertEqual(result["evidence"][0]["score"], 1)
        self.assertEqual(self.client.calls[-1], ([query], er.QUERY_PROMPT))
        furniture = self.retriever().retrieve(self.catalog, query, scope="furniture", top_k=3)
        self.assertEqual([p["key"] for p in furniture["positions"]], ["chair@1", "chair@2"])

    def test_deduplicated_cache_survives_restart_and_only_query_is_embedded_again(self):
        index = self.retriever()
        self.assertEqual(self.client.calls, [])  # Lazy startup.
        index.retrieve(self.catalog, "Табуретка")
        self.assertEqual(len([call for call in self.client.calls if call[1] == er.DOCUMENT_PROMPT]), 2)
        index.retrieve(self.catalog, "Табуретка")
        self.assertEqual(len(self.client.calls), 4)  # Two document batches, two queries.
        restarted = FakeClient()
        self.retriever(restarted).retrieve(self.catalog, "Табуретка")
        self.assertEqual(restarted.calls, [(["Табуретка"], er.QUERY_PROMPT)])

    def test_changed_names_or_model_and_corrupt_cache_rebuild(self):
        self.retriever().retrieve(self.catalog, "Табуретка")
        self.catalog["positions"].append({"key": "table@1", "name": "Стол", "domains": ["furniture"]})
        self.client.calls.clear()
        self.retriever().retrieve(self.catalog, "Табуретка")
        self.assertEqual(sum(call[1] == er.DOCUMENT_PROMPT for call in self.client.calls), 3)
        changed = FakeClient()
        changed.model_id = "different-model"
        self.retriever(changed).retrieve(self.catalog, "Табуретка")
        self.assertEqual(sum(call[1] == er.DOCUMENT_PROMPT for call in changed.calls), 3)
        self.cache.write_text("broken")
        changed.calls.clear()
        self.retriever(changed).retrieve(self.catalog, "Табуретка")
        self.assertEqual(sum(call[1] == er.DOCUMENT_PROMPT for call in changed.calls), 3)

    def test_failed_build_does_not_publish_partial_cache_and_can_recover(self):
        index = self.retriever()
        with patch.object(self.client, "embed", side_effect=[[[2, 0]], er.EmbeddingError("offline")]):
            with self.assertRaises(er.EmbeddingError):
                index.retrieve(self.catalog, "Табуретка")
        self.assertFalse(self.cache.exists())
        self.assertEqual(index.retrieve(self.catalog, "Табуретка")["positions"][0]["key"], "chair@1")

    def test_simultaneous_first_queries_build_catalog_once(self):
        index = self.retriever()
        barrier = Barrier(2)
        embed = self.client.embed

        def wait_for_both_queries(texts, prompt):
            if prompt == er.QUERY_PROMPT:
                barrier.wait(timeout=5)
            return embed(texts, prompt)

        with patch.object(self.client, "embed", side_effect=wait_for_both_queries):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(index.retrieve, self.catalog, "Табуретка") for _ in range(2)]
                for future in futures:
                    self.assertEqual(future.result()["positions"][0]["key"], "chair@1")
        self.assertEqual(sum(call[1] == er.DOCUMENT_PROMPT for call in self.client.calls), 2)
        self.assertEqual(sum(call[1] == er.QUERY_PROMPT for call in self.client.calls), 2)

    def test_empty_scope_needs_no_service_or_cache(self):
        self.client.fail = True
        result = self.retriever().retrieve(self.catalog, "Куртка", scope="clothing")
        self.assertEqual(result["positions"], [])
        self.assertEqual(self.client.calls, [])
        self.assertFalse(self.cache.exists())

    def test_query_dimension_mismatch_is_explicit(self):
        index = self.retriever()
        index.retrieve(self.catalog, "Табуретка")
        with patch.object(self.client, "embed", return_value=[[1, 0, 0]]):
            with self.assertRaisesRegex(er.EmbeddingError, "dimensions differ"):
                index.retrieve(self.catalog, "Табуретка")


if __name__ == "__main__":
    unittest.main()
