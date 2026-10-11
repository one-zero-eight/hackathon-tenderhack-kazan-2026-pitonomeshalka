"""Submission must finish before inference, and polling must not repeat GPU work."""

import asyncio
import json
from threading import Event
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
import httpx

from backend.src.app import model_busy_handler
from backend.src import pipeline
from backend.src.models import KtruPosition
from backend.src.retrieval import Retrieval
from backend.src.routes import get_pipeline_service, router
from backend.src.schemas import AnalysisRequest
from backend.src.service import ModelBusy, PipelineService
from backend.src.settings import Settings
from backend.tests.memory_store import MemoryStore


class AnalysisJobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = MemoryStore()
        self.service = PipelineService(Settings(), store=self.store)
        self.service.retriever = Mock()
        position = KtruPosition(import_sha256="fixture", code="drill", version=1,
                                name="Дрель", characteristics=[])
        self.service.prepare = Mock(return_value=pipeline.prepare(
            Retrieval("fixture", [position], [], 1, False), "дрель"))
        self.started = Event()
        self.release = Event()

        def run_jobs(*args):
            self.started.set()
            if not self.release.wait(5):
                raise RuntimeError("Test worker was not released")
            return [], "Classifier connection lost"

        self.service._run_jobs = Mock(side_effect=run_jobs)
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.add_exception_handler(ModelBusy, model_busy_handler)
        self.app.dependency_overrides[get_pipeline_service] = lambda: self.service
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)
        self.addCleanup(self.service.close)
        self.addCleanup(self.release.set)

    async def submit_until_response(self, fail_delivery=False):
        # Observe the HTTP response directly while the model worker is blocked.
        sent = []
        delivered = asyncio.Event()
        body = json.dumps({"text": "дрель"}).encode()

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            sent.append(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                delivered.set()
                if fail_delivery:
                    raise ConnectionError("Client disconnected during submission")

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": "/analyses", "raw_path": b"/analyses",
                 "query_string": b"", "root_path": "", "headers": [(b"content-type", b"application/json")],
                 "client": ("127.0.0.1", 1), "server": ("test", 80)}
        task = asyncio.create_task(self.app(scope, receive, send))
        await asyncio.wait_for(delivered.wait(), 2)
        self.assertEqual(sent[0]["status"], 202)
        payload = json.loads(sent[1]["body"])
        self.assertEqual(payload["status"], "running")
        return payload["run_id"], task

    async def test_response_precedes_inference_and_disconnected_poll_can_resume(self):
        run_id, task = await self.submit_until_response()
        try:
            self.assertTrue(self.service.model_lock.locked())
            pending = await self.client.get(f"/analyses/{run_id}")
            self.assertEqual(pending.json()["status"], "running")
            self.assertEqual(pending.headers["cache-control"], "no-store")
            # A concurrent submission must be rejected before another job starts.
            competing = await self.client.post("/analyses", json={"text": "другая дрель"})
            self.assertEqual(competing.status_code, 503)
            self.assertEqual(len(self.store.runs), 1)
            self.release.set()
            await asyncio.wait_for(task, 2)
            await asyncio.to_thread(self.service.close)
            recovered = (await self.client.get(f"/analyses/{run_id}")).json()
            self.assertEqual(recovered["status"], "failed")
            self.assertEqual(recovered["error"], "Classifier connection lost")
            self.assertEqual(recovered["result"]["run_id"], run_id)
            self.assertFalse(recovered["result"]["complete_inference"])
            self.assertFalse(self.service.model_lock.locked())
            self.service._run_jobs.assert_called_once()
            saved = await self.client.get(f"/results/{run_id}")
            self.assertEqual(saved.status_code, 200)
        finally:
            self.release.set()
            await task

    async def test_completed_job_and_unknown_or_invalid_ids(self):
        self.service.prepare.return_value = pipeline.prepare(Retrieval("fixture", [], [], 0, False), "дрель")
        self.service._run_jobs.return_value = ([], None)
        self.service._run_jobs.side_effect = None
        accepted = await self.client.post("/analyses", json={"text": "дрель"})
        self.assertEqual(accepted.status_code, 202)
        run_id = accepted.json()["run_id"]
        await asyncio.to_thread(self.service.close)
        completed = (await self.client.get(f"/analyses/{run_id}")).json()
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"]["status"], "retrieval_miss")
        self.assertEqual((await self.client.get("/analyses/not-a-run")).status_code, 422)
        self.assertEqual((await self.client.get("/analyses/20261011T000000000000Z_" + "0" * 32)).status_code, 404)
        invalid = await self.client.post("/analyses", json={"text": "   "})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(len(self.store.runs), 1)

    async def test_unexpected_worker_failure_is_saved_and_releases_lock(self):
        self.service.prepare.side_effect = RuntimeError("Retrieval unavailable")
        accepted = await self.client.post("/analyses", json={"text": "дрель"})
        run_id = accepted.json()["run_id"]
        await asyncio.to_thread(self.service.close)
        failed = (await self.client.get(f"/analyses/{run_id}")).json()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"], "Retrieval unavailable")
        self.assertIsNone(failed["result"])
        self.assertFalse(self.service.model_lock.locked())

    async def test_failed_response_delivery_does_not_orphan_the_lock(self):
        run_id, task = await self.submit_until_response(fail_delivery=True)
        with self.assertRaisesRegex(ConnectionError, "Client disconnected"):
            await task
        self.assertTrue(self.service.model_lock.locked())
        self.release.set()
        await asyncio.to_thread(self.service.close)
        self.assertFalse(self.service.model_lock.locked())
        self.assertEqual(self.store.runs[run_id]["status"], "failed")
        self.service._run_jobs.assert_called_once()

    async def test_failed_submission_releases_lock(self):
        self.store.begin_run = Mock(side_effect=RuntimeError("Database unavailable"))
        with self.assertRaisesRegex(RuntimeError, "Database unavailable"):
            self.service.start_analysis(AnalysisRequest(text="дрель"))
        self.assertFalse(self.service.model_lock.locked())

    async def test_slow_database_does_not_delay_submission_or_active_polling(self):
        original = self.store.begin_run
        persist_release = Event()
        self.addCleanup(persist_release.set)

        def slow_begin(*args):
            if not persist_release.wait(5):
                raise RuntimeError("Test database was not released")
            original(*args)

        self.store.begin_run = slow_begin
        self.store.get_run = Mock(side_effect=AssertionError("Active polling must not query PostgreSQL"))
        run_id, task = await self.submit_until_response()
        try:
            self.assertNotIn(run_id, self.store.runs)
            status = await self.client.get(f"/analyses/{run_id}")
            self.assertEqual(status.json()["status"], "running")
            self.assertTrue(self.service.model_lock.locked())
        finally:
            persist_release.set()
            self.release.set()
            await task
            await asyncio.to_thread(self.service.close)
        self.assertEqual(self.store.runs[run_id]["status"], "failed")

    async def test_background_database_failure_is_visible_to_polling(self):
        self.store.begin_run = Mock(side_effect=RuntimeError("Database unavailable"))
        response = await self.client.post("/analyses", json={"text": "дрель"})
        self.assertEqual(response.status_code, 202)
        await asyncio.to_thread(self.service.close)
        status = (await self.client.get("/analyses/" + response.json()["run_id"])).json()
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["error"], "Database unavailable")
        self.assertFalse(self.service.model_lock.locked())
