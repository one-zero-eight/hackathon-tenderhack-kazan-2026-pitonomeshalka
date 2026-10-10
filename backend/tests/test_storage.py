"""Opt-in integration tests using isolated schemas in the configured PostgreSQL."""

from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg import Error, sql

from backend.src.app import create_app
from backend.src.migrate import import_files
from backend.src.settings import Settings
from backend.src.storage import PostgresStore, current_run, digest
from backend.tests.test_api import FakeEmbedder, FakeModel, catalog_fixture
from experiments.embedding_retrieval import MeowEmbedClient, EmbeddingError


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "Set RUN_POSTGRES_TESTS=1 with PostgreSQL running")
class PostgresTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.settings = replace(Settings(), results_dir=Path(self.directory) / "runs",
                                catalog_path=Path(self.directory) / "catalog.json",
                                embedding_cache_path=Path(self.directory) / "vectors.json",
                                startup_log_path=Path(self.directory) / "startup.jsonl")
        self.schema = "test_" + uuid4().hex
        self.store = PostgresStore(self.settings, schema=self.schema)
        self.store.initialize()
        self.addCleanup(self.cleanup_schema)

    def cleanup_schema(self):
        with self.store.pool.connection() as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
        self.store.close()

    def make_app(self, model, embedder, loader=None):
        return create_app(self.settings, catalog_loader=loader or (lambda _: catalog_fixture()),
                          client_factory=model.factory, embedding_client_factory=embedder.factory,
                          store_factory=lambda settings: PostgresStore(settings, schema=self.schema))

    def test_migrations_idempotent_and_catalog_persistent(self):
        catalog = catalog_fixture()
        fingerprint = self.store.save_catalog(catalog, self.settings.catalog_key)
        reopened = PostgresStore(self.settings, schema=self.schema)
        try:
            reopened.initialize()
            self.assertEqual(reopened.get_catalog(self.settings.catalog_key), catalog)
            self.assertEqual(reopened.save_catalog(catalog), fingerprint)
            with reopened.pool.connection() as conn:
                self.assertEqual(conn.execute("SELECT count(*) AS n FROM catalog_positions").fetchone()["n"], 2)
                self.assertEqual(conn.execute("SELECT count(*) AS n FROM catalog_facts").fetchone()["n"], 2)
                self.assertEqual(conn.execute("SELECT count(*) AS n FROM backend_schema_migrations").fetchone()["n"], 1)
        finally:
            reopened.close()

    def test_pgvector_cosine_scope_and_atomic_index_replacement(self):
        metadata = dict(model="fixture", names=["chair", "drill"])
        fingerprint = digest(metadata)
        self.store.save_embedding_index(fingerprint, metadata, [[0, 1, 0], [1, 0, 0]])
        self.assertEqual(self.store.score_embeddings(fingerprint, [0, 1, 0], ["chair", "drill"]), {"chair": 1., "drill": 0.})
        self.assertEqual(self.store.score_embeddings(fingerprint, [0, 1, 0], ["drill"]), {"drill": 0.})
        with self.assertRaises(Error):
            self.store.save_embedding_index(fingerprint, dict(model="fixture", names=["chair", "chair"]), [[1, 0, 0], [1, 0, 0]])
        self.assertEqual(self.store.load_embedding_index(fingerprint), {"metadata": metadata, "vectors": [[0, 1, 0], [1, 0, 0]]})

    def test_migration_checksum_mismatch_is_rejected(self):
        with self.store.pool.connection() as conn:
            conn.execute("UPDATE backend_schema_migrations SET sha256='changed' WHERE version=1")
        reopened = PostgresStore(self.settings, schema=self.schema)
        with self.assertRaisesRegex(ValueError, "Applied migration 1 was modified"):
            reopened.initialize()

    def test_api_evidence_committed_before_dispatch_and_survives_restart(self):
        model, embedder = FakeModel(), FakeEmbedder()
        original_infer = model.infer

        def inspect_then_infer(body):
            with self.store.pool.connection() as conn:
                calls = conn.execute("SELECT request,status,record FROM model_calls ORDER BY ordinal").fetchall()
            self.assertEqual(len(calls), len(model.calls) + 1)
            self.assertEqual(calls[-1]["status"], "running")
            self.assertIsNone(calls[-1]["record"])
            self.assertEqual(calls[-1]["request"], body)
            for qid, question in body["questions"].items():
                self.assertEqual(list(calls[-1]["request"]["questions"][qid]["criteria"]), list(question["criteria"]))
            return original_infer(body)

        app = self.make_app(model, embedder)
        with TestClient(app) as client, patch.object(model, "infer", side_effect=inspect_then_infer), redirect_stdout(io.StringIO()):
            response = client.post("/analyze", json={"text": "Аккумуляторная дрель 18 В"})
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
        run = self.store.get_run(result["run_id"])
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["result"], result)
        self.assertEqual(run["analysis"]["successful_requests"], 3)
        self.assertFalse(self.settings.results_dir.exists())
        self.assertFalse(self.settings.embedding_cache_path.exists())
        self.assertFalse(self.settings.startup_log_path.exists())
        embedder.calls.clear()
        model.calls.clear()
        with patch("backend.src.service.load_catalog", side_effect=AssertionError("Should load from DB")) as loader:
            restarted = self.make_app(model, embedder, loader)
            with TestClient(restarted) as client:
                self.assertEqual(client.get("/results/" + result["run_id"]).json(), result)
                self.assertEqual(model.calls, [])
                self.assertEqual(embedder.calls, [])
                self.assertEqual(client.post("/preview", json={"text": "Аккумуляторная дрель"}).status_code, 200)
                self.assertEqual(len(embedder.calls), 1)  # Query only; catalog vectors loaded from PostgreSQL.
                self.assertEqual(restarted.state.pipeline.retriever._ensure_index()["status"], "memory")
        with self.store.pool.connection() as conn:
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM connection_checks").fetchone()["n"], 4)

    def test_partial_failure_and_embedding_failure_are_retained(self):
        model, embedder = FakeModel(), FakeEmbedder()
        model.fail_at = 2
        with TestClient(self.make_app(model, embedder)) as client, redirect_stdout(io.StringIO()):
            failed = client.post("/analyze", json={"text": "Аккумуляторная дрель 18 В"})
            self.assertEqual(failed.status_code, 502)
            result = failed.json()["detail"]["result"]
            self.assertEqual(client.get("/results/" + result["run_id"]).json(), result)
            self.assertFalse(result["complete_inference"])
            self.assertEqual(self.store.get_run(result["run_id"])["status"], "failed")
            embedder.offline = True
            self.assertEqual(client.post("/analyze", json={"text": "Дрель"}).status_code, 502)
        with self.store.pool.connection() as conn:
            self.assertEqual([r["status"] for r in conn.execute("SELECT status FROM model_calls ORDER BY ordinal")], ["succeeded", "failed"])
            runs = conn.execute("SELECT status,error,result FROM analysis_runs ORDER BY created_at").fetchall()
            self.assertEqual(runs[-1]["status"], "failed")
            self.assertIsNone(runs[-1]["result"])
            self.assertIn("Embedding retrieval failed", runs[-1]["error"])

    def test_embedding_payload_and_timings_saved_on_success_and_failure(self):
        run_id = "20261010T123456000000Z_" + uuid4().hex
        self.store.begin_run(run_id, {"text": "Стул"})
        client = MeowEmbedClient()
        client.recorder = self.store
        token = current_run.set(run_id)
        try:
            with patch.object(client, "_embed", return_value=[[0, 1, 0]]):
                client.embed(["Стул"], "test prompt")
            with patch.object(client, "_embed", side_effect=EmbeddingError("offline")), self.assertRaises(EmbeddingError):
                client.embed(["Табуретка"], "test prompt")
        finally:
            current_run.reset(token)
        with self.store.pool.connection() as conn:
            calls = conn.execute("SELECT * FROM embedding_calls ORDER BY id").fetchall()
        self.assertEqual([call["status"] for call in calls], ["succeeded", "failed"])
        self.assertEqual(calls[0]["request"]["texts"], ["Стул"])
        self.assertEqual(calls[0]["dimensions"], 3)
        self.assertEqual(calls[1]["error"], "offline")
        self.assertTrue(all(call["run_id"] == run_id and call["elapsed_seconds"] >= 0 for call in calls))

    def test_legacy_import_idempotent_and_preserves_order_and_results(self):
        catalog = catalog_fixture()
        self.settings.catalog_path.write_text(json.dumps(catalog))
        metadata = dict(model="fixture", names=["chair", "drill"])
        self.settings.embedding_cache_path.write_text(json.dumps(dict(metadata=metadata, vectors=[[0, 1, 0], [1, 0, 0]])))
        run_id = "20261010T123456000000Z_" + uuid4().hex
        folder = self.settings.results_dir / run_id
        folder.mkdir(parents=True)
        request = {"state": "Нужна дрель", "questions": {"fact": {"criteria": {"z": "first", "a": "second"}}}}
        outgoing = dict(logged_at=datetime.now(timezone.utc).isoformat(), id="test", experiment="facts", method="POST", url="http://fake/v1/systemone", request=request)
        record = dict(id="test", experiment="facts", request=request, error="offline")
        result = dict(run_id=run_id, complete_inference=False)
        (folder / "model_requests.jsonl").write_text(json.dumps(outgoing) + "\n")
        (folder / "requests.jsonl").write_text(json.dumps(record) + "\n")
        (folder / "response.json").write_text(json.dumps(result))
        (folder / "analysis.json").write_text(json.dumps(dict(catalog_sha256=digest(catalog), planned_requests=2, planned_questions=3)))
        self.assertEqual(import_files(self.store, self.settings), dict(catalogs=1, embedding_indexes=1, runs=1))
        self.assertEqual(import_files(self.store, self.settings), dict(catalogs=0, embedding_indexes=0, runs=0))
        self.assertEqual(self.store.get_run(run_id)["result"], result)
        self.assertEqual(self.store.get_run(run_id)["status"], "failed")
        self.assertTrue((folder / "response.json").exists())
        with self.store.pool.connection() as conn:
            call = conn.execute("SELECT request,outgoing,record FROM model_calls").fetchone()
        self.assertEqual(call["record"], record)
        self.assertEqual(call["outgoing"], outgoing)
        self.assertEqual(list(call["request"]["questions"]["fact"]["criteria"]), ["z", "a"])
