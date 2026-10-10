from copy import deepcopy
from dataclasses import replace
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from psycopg import OperationalError

from backend.src.app import create_app
from backend.src.service import load_catalog
from backend.src.settings import Settings
from experiments import classifier_experiments as ce
from experiments.embedding_retrieval import EmbeddingError
from backend.tests.memory_store import MemoryStore


def catalog_fixture():
    positions, facts = [], []
    for code, power in (("battery", "От аккумулятора"), ("mains", "От сети")):
        position = dict(key=code + "@1", code=code, version="1",
                        name="Дрель ручная электрическая", domains=["tools"],
                        source="fixture.xml", no_new_features="true",
                        characteristics=[dict(code="power", name="Тип питания", type="1",
                                              kind="1", required=True,
                                              values=[dict(text=power, unit_code="")])])
        if code == "battery":
            position["characteristics"].append(dict(
                code="voltage", name="Напряжение аккумулятора", type="2", kind="2", required=True,
                values=[dict(text="", unit_code="222", exact=[], ranges=[dict(
                    min="12", max="20", minMathNotation="greaterOrEqual", maxMathNotation="less")])],
            ))
        positions.append(position)
        facts.append(dict(id=code, name="Тип питания", value=power, unit_code="",
                          sources=[dict(position=position["key"], characteristic_code="power", value_ordinal=0)]))
    return dict(positions=positions, facts=facts)


class FakeModel:
    def __init__(self):
        self.health_calls = 0
        self.calls = []
        self.fail_at = None
        self.offline = False
        self.overrides = {}
        self.base_url = "http://fake"
        self.timeout = 1

    def factory(self, base_url, timeout):
        self.base_url, self.timeout = base_url, timeout
        return self

    def health(self):
        self.health_calls += 1
        if self.offline:
            raise RuntimeError("model unavailable")
        return dict(model=ce.MODEL)

    def infer(self, body):
        self.calls.append(body)
        if len(self.calls) == self.fail_at:
            raise RuntimeError("inference timed out")
        answers = {}
        for qid, question in body["questions"].items():
            logical_qid = qid.split("__", 1)[-1]
            choices = question["criteria"]
            choice = "span_0" if logical_qid == "measurement" else "contradicted" if logical_qid == "mains" else "supported"
            choice, confidence = self.overrides.get(logical_qid, (choice, .95))
            answers[qid] = dict(choice=choice, probabilities={
                key: confidence if key == choice else (1 - confidence) / (len(choices) - 1) for key in choices
            })
        return dict(request=body, response=dict(model=ce.MODEL, answers=answers), elapsed_seconds=.01)


class FakeEmbedder:
    def __init__(self):
        self.calls = []
        self.health_calls = 0
        self.offline = False

    def factory(self, base_url, model_id, timeout):
        self.base_url, self.model_id, self.timeout = base_url, model_id, timeout
        return self

    def embed(self, texts, prompt):
        self.calls.append((list(texts), prompt))
        if self.offline:
            raise EmbeddingError("embedder unavailable")
        return [[0, 1, 0] if any(word in text.casefold() for word in ("табур", "стул"))
                else [1, 0, 0] for text in texts]

    def health(self):
        self.health_calls += 1
        if self.offline:
            raise EmbeddingError("embedder unavailable")
        return dict(id=self.model_id, type="dense", dimensions=3)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = Settings(classifier_batch_size=0, results_dir=Path(self.directory.name) / "runs",
                                 startup_log_path=Path(self.directory.name) / "startup.jsonl",
                                 embedding_cache_path=Path(self.directory.name) / "embeddings.json")
        self.store = MemoryStore()
        self.model = FakeModel()
        self.embedder = FakeEmbedder()
        self.catalog = catalog_fixture()
        self.load_count = 0

        def loader(settings):
            self.load_count += 1
            return deepcopy(self.catalog)

        self.app = create_app(self.settings, catalog_loader=loader, client_factory=self.model.factory,
                              embedding_client_factory=self.embedder.factory, store_factory=lambda _: self.store)
        self.client = self.enterContext(TestClient(self.app))
        self.body = dict(text="  Аккумуляторная дрель 0,018 кВ.", scope="drills")

    def test_health_loads_catalog_once_and_does_not_repeat_startup_probes(self):
        for _ in range(2):
            response = self.client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "ok", "model_busy": False})
        self.assertEqual(self.load_count, 1)
        self.assertEqual(self.model.health_calls, 1)
        self.assertEqual(self.embedder.health_calls, 1)
        self.assertEqual(self.embedder.calls, [])

    def test_database_failure_prevents_startup_and_closes_pool(self):
        store = MemoryStore()
        app = create_app(self.settings, store_factory=lambda _: store)
        with patch.object(store, "initialize", side_effect=OperationalError("database offline")), \
                patch.object(store, "close") as close, self.assertRaisesRegex(OperationalError, "database offline"):
            with TestClient(app):
                self.fail("Startup must require PostgreSQL")
        close.assert_called_once()

    def test_database_runtime_failure_returns_503(self):
        run_id = "20261010T123456000000Z_" + "0" * 32
        with patch.object(self.store, "get_run", side_effect=OperationalError("database offline")), \
                self.assertLogs("uvicorn.error", level="ERROR"):
            response = self.client.get("/results/" + run_id)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["error"], "Database unavailable")

    def test_preview_returns_only_plan_counts_and_candidate_identifiers(self):
        response = self.client.post("/preview", json=self.body)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(set(result), {"planned_requests", "planned_questions", "candidates"})
        self.assertEqual(result["planned_requests"], 3)
        self.assertEqual(result["planned_questions"], 4)
        self.assertTrue(all(set(candidate) == {"code", "version", "name"} for candidate in result["candidates"]))
        self.assertEqual(self.model.health_calls, 1)
        self.assertEqual(self.model.calls, [])
        self.assertFalse(self.settings.results_dir.exists())
        self.assertTrue(self.store.indexes)
        self.assertFalse(self.settings.embedding_cache_path.exists())

    def test_analysis_reuses_numeric_rules_extras_and_saves_evidence(self):
        body = dict(self.body, extras=[dict(name="Цвет", value="Синий")])
        response = self.client.post("/analyze", json=body)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["complete_inference"])
        self.assertEqual(result["recommended_candidate"], "battery@1")
        self.assertTrue(result["requires_review"])
        self.assertEqual(result["status"], "ready_for_review")
        self.assertIsNone(result["clarifying_question"])
        self.assertIn({"name": "Напряжение аккумулятора", "value": "18 В"}, result["properties"])
        battery = result["candidates"][0]
        self.assertEqual(battery["status"], "compatible")
        self.assertEqual(battery["extra_characteristics"][0]["action"], "do_not_add")
        run_id = result["run_id"]
        self.assertEqual(self.store.runs[run_id]["result"], result)
        details = self.store.runs[run_id]["analysis"]
        self.assertEqual(details["successful_requests"], 3)
        self.assertEqual(details["analysis"]["retrieval"]["method"], "embedding")
        self.assertEqual(details["analysis"]["retrieval"]["model"], "google/embeddinggemma-2")
        self.assertIsNone(details["analysis"]["final_code"])
        raw_battery = next(c for c in details["analysis"]["candidates"] if c["code"] == "battery")
        self.assertEqual(raw_battery["extra_characteristics"][0]["origin"], "user_supplied")
        span = raw_battery["numeric_checks"][0]["span"]
        self.assertEqual(span["value"], "18.000")
        self.assertEqual(self.body["text"][span["start"]:span["end"]], span["raw"])
        self.assertEqual(len(self.store.calls[run_id]), 3)
        outgoing = [call["outgoing"] for call in self.store.calls[run_id]]
        self.assertEqual([entry["request"] for entry in outgoing], self.model.calls)
        self.assertTrue(all(entry["url"] == self.settings.classifier_base_url + "/v1/systemone" for entry in outgoing))
        self.assertEqual(self.store.artifacts[run_id]["manifest.json"]["catalog_sha256"], details["catalog_sha256"])

    def test_model_requests_are_logged_before_dispatch_including_failed_call(self):
        self.model.fail_at = 2
        infer = self.model.infer

        def check_log_then_infer(body):
            run_id = next(iter(self.store.runs))
            outgoing = [call["outgoing"] for call in self.store.calls[run_id]]
            # The pending call must already be visible to another reader.
            self.assertEqual(len(outgoing), len(self.model.calls) + 1)
            self.assertEqual(outgoing[-1]["request"], body)
            self.assertEqual(outgoing[-1]["method"], "POST")
            self.assertTrue(outgoing[-1]["logged_at"])
            return infer(body)

        with patch.object(self.model, "infer", side_effect=check_log_then_infer), \
                self.assertLogs("uvicorn.error", level="DEBUG") as console:
            response = self.client.post("/analyze", json=self.body)
        self.assertEqual(response.status_code, 502)
        run_id = response.json()["detail"]["result"]["run_id"]
        outgoing = [call["outgoing"] for call in self.store.calls[run_id]]
        completed = [call["record"] for call in self.store.calls[run_id]]
        self.assertEqual(len(outgoing), 2)
        self.assertEqual([entry["id"] for entry in outgoing], [entry["id"] for entry in completed])
        self.assertIn("error", completed[-1])
        console_requests = [json.loads(entry.getMessage().removeprefix("Model request payload: "))
                            for entry in console.records if entry.getMessage().startswith("Model request payload: ")]
        self.assertEqual(console_requests, outgoing)
        self.assertTrue(all(entry.levelname == "DEBUG" for entry in console.records
                            if entry.getMessage().startswith("Model request payload: ")))
        self.assertIn(self.body["text"], "\n".join(console.output))

    def test_info_model_logs_are_concise_and_evidence_stays_complete(self):
        stdout = io.StringIO()
        with self.assertLogs("uvicorn.error", level="INFO") as console, redirect_stdout(stdout):
            result = self.client.post("/analyze", json=self.body).json()
        entries = [entry.getMessage() for entry in console.records if entry.getMessage().startswith("Model request:")]
        self.assertEqual(len(entries), 3)
        self.assertIn("1/3", entries[0])
        self.assertIn("run_id=" + result["run_id"], entries[0])
        self.assertIn("questions=1", entries[0])
        self.assertTrue(all(len(message) < 250 for message in entries))
        self.assertNotIn(self.body["text"], "\n".join(console.output))
        self.assertNotIn('"criteria"', "\n".join(console.output))
        self.assertNotIn("Model request payload:", "\n".join(console.output))
        self.assertNotIn("Model request:", stdout.getvalue())
        outgoing = [call["outgoing"]["request"] for call in self.store.calls[result["run_id"]]]
        self.assertEqual(outgoing, self.model.calls)

    def test_batching_preserves_result_and_commits_one_complete_wire_request(self):
        baseline = self.client.post("/analyze", json=self.body).json()
        self.model.calls.clear()
        service = self.app.state.pipeline
        service.settings = replace(service.settings, classifier_batch_size=16)
        self.assertEqual(self.client.post("/preview", json=self.body).json()["planned_requests"], 1)
        infer = self.model.infer

        def inspect_before_dispatch(body):
            run_id = next(reversed(self.store.runs))
            calls = self.store.calls[run_id]
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["outgoing"]["request"], body)
            self.assertEqual(len(body["questions"]), 4)
            return infer(body)

        with patch.object(self.model, "infer", side_effect=inspect_before_dispatch):
            response = self.client.post("/analyze", json=self.body)
        self.assertEqual(response.status_code, 200, response.text)
        batched = response.json()
        self.assertEqual({k: v for k, v in baseline.items() if k != "run_id"},
                         {k: v for k, v in batched.items() if k != "run_id"})
        self.assertEqual(len(self.model.calls), 1)
        details = self.store.runs[batched["run_id"]]["analysis"]
        self.assertEqual(details["planned_requests"], 1)
        self.assertEqual(details["successful_requests"], 1)
        record = self.store.calls[batched["run_id"]][0]["record"]
        self.assertEqual(len(record["parts"]), 3)
        self.assertEqual(set(record["response"]["answers"]), set(self.model.calls[0]["questions"]))

    def test_failed_batch_keeps_earlier_evidence_and_stops_dispatch(self):
        self.app.state.pipeline.settings = replace(self.settings, classifier_batch_size=2)
        self.model.fail_at = 2
        response = self.client.post("/analyze", json=self.body)
        self.assertEqual(response.status_code, 502)
        result = response.json()["detail"]["result"]
        self.assertFalse(result["complete_inference"])
        self.assertEqual(len(self.model.calls), 2)
        calls = self.store.calls[result["run_id"]]
        self.assertIn("response", calls[0]["record"])
        self.assertIn("error", calls[1]["record"])
        self.assertEqual(len(calls[1]["record"]["parts"]), 1)
        self.assertEqual(self.client.get("/results/" + result["run_id"]).json(), result)

    def test_missing_required_information_remains_visible(self):
        response = self.client.post("/analyze", json=dict(text="Аккумуляторная дрель", scope="drills"))
        self.assertEqual(response.status_code, 200)
        analysis = response.json()
        battery = next(c for c in analysis["candidates"] if c["code"] == "battery")
        self.assertEqual(battery["missing_required"], ["Напряжение аккумулятора"])
        self.assertIn("Напряжение аккумулятора", analysis["clarifying_question"])

    def test_retrieval_miss_does_not_require_model(self):
        self.model.offline = True
        self.embedder.offline = True
        response = self.client.post("/analyze", json=dict(text="Табуретка", scope="furniture"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "retrieval_miss")
        self.assertEqual(self.model.health_calls, 1)
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.embedder.calls, [])

    def test_semantic_retrieval_finds_candidate_without_shared_words(self):
        chair = deepcopy(self.catalog["positions"][0])
        chair.update(key="chair@1", code="chair", name="Стул", domains=["furniture"], characteristics=[])
        self.app.state.pipeline.catalog["positions"].append(chair)
        response = self.client.post("/preview", json={"text": "Табуретка", "scope": "furniture"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["candidates"], [{"code": "chair", "version": "1", "name": "Стул"}])
        self.assertEqual(self.model.calls, [])
        response = self.client.post("/analyze", json={"text": "Табуретка", "scope": "furniture"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommended_candidate"], "chair@1")
        question = next(iter(self.model.calls[0]["questions"].values()))
        self.assertIn("Вид самого товара = Стул", question["instructions"])

    def test_embedder_failure_is_502_and_does_not_call_classifier(self):
        self.embedder.offline = True
        for endpoint in ("/preview", "/analyze"):
            response = self.client.post(endpoint, json=self.body)
            self.assertEqual(response.status_code, 502)
            self.assertIn("Embedding retrieval failed", response.json()["detail"]["error"])
            self.assertIsNone(response.json()["detail"]["result"])
        self.assertEqual(self.model.health_calls, 1)
        self.assertEqual(self.model.calls, [])
        self.assertFalse(self.settings.results_dir.exists())
        self.assertFalse(self.settings.embedding_cache_path.exists())
        self.assertFalse(self.app.state.pipeline.model_lock.locked())
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.embedder.offline = False
        self.assertEqual(self.client.post("/preview", json=self.body).status_code, 200)

    def test_input_validation_rejects_invalid_and_server_only_fields(self):
        for changes in (dict(text=" \t"), dict(scope="other"), dict(top_k=0), dict(top_k=33),
                        dict(chunk_size=9), dict(threshold=1.1), dict(base_url="http://other"),
                        dict(extras=[dict(name=" ", value="blue")])):
            with self.subTest(changes=changes):
                response = self.client.post("/analyze", json=dict(self.body, **changes))
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.model.health_calls, 1)

    def test_question_budget_fails_before_classifier_or_run_files(self):
        app = create_app(replace(self.settings, max_questions=1),
                         catalog_loader=lambda _: self.catalog, client_factory=self.model.factory,
                         embedding_client_factory=self.embedder.factory, store_factory=lambda _: self.store)
        with TestClient(app) as client:
            response = client.post("/analyze", json=self.body)
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"][0]
        self.assertEqual(detail["loc"], ["body"])
        self.assertIn("BACKEND_MAX_QUESTIONS", detail["msg"])
        self.assertEqual(self.model.health_calls, 2)  # Two application startups, no inference health checks.
        self.assertFalse(self.settings.results_dir.exists())

    def test_busy_model_rejects_second_run_but_health_and_preview_work(self):
        service = self.app.state.pipeline
        with service.model_lock:
            for path, method in (("/analyze", "post"), ("/health/model", "get")):
                response = getattr(self.client, method)(path, **(dict(json=self.body) if method == "post" else {}))
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.headers["retry-after"], "5")
            self.assertTrue(self.client.get("/health").json()["model_busy"])
            self.assertEqual(self.client.post("/preview", json=self.body).status_code, 200)
        self.assertEqual(self.model.health_calls, 1)

    def test_startup_logs_both_connections_without_embedding_or_inference(self):
        records = self.store.checks
        self.assertEqual([record["service"] for record in records], ["classifier", "embedder"])
        self.assertTrue(all(record["status"] == "ok" for record in records))
        self.assertEqual(records[0]["url"], self.settings.classifier_base_url + "/health")
        self.assertEqual(records[1]["url"], self.settings.embedding_base_url + "/models")
        self.assertEqual(records[1]["details"]["dimensions"], 3)
        self.assertTrue(all(record["checked_at"] and record["elapsed_seconds"] >= 0 for record in records))
        self.assertEqual(self.app.state.startup_connections, records)
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.embedder.calls, [])
        self.assertFalse(self.settings.embedding_cache_path.exists())
        self.assertFalse(self.settings.results_dir.exists())

    def test_startup_failures_are_logged_and_backend_still_starts(self):
        self.model.offline = self.embedder.offline = True
        settings = replace(self.settings, startup_check_timeout_seconds=.25)
        app = create_app(settings, catalog_loader=lambda _: self.catalog,
                         client_factory=self.model.factory, embedding_client_factory=self.embedder.factory, store_factory=lambda _: self.store)
        with self.assertLogs("uvicorn.error", level="INFO") as console, TestClient(app) as client:
            self.assertEqual(client.get("/health").status_code, 200)
        records = self.store.checks
        self.assertEqual(len(records), 4)  # Append instead of overwriting the prior startup.
        self.assertTrue(all(record["status"] == "error" for record in records[-2:]))
        self.assertTrue(all(record["timeout_seconds"] == .25 for record in records[-2:]))
        self.assertEqual(records[-2]["error"], "model unavailable")
        self.assertEqual(records[-1]["error"], "embedder unavailable")
        self.assertTrue(any("classifier FAILED" in line for line in console.output))
        self.assertTrue(any("embedder FAILED" in line for line in console.output))
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.embedder.calls, [])
        self.assertFalse(settings.embedding_cache_path.exists())

    def test_startup_model_mismatch_is_logged_as_failure(self):
        app = create_app(self.settings, catalog_loader=lambda _: self.catalog,
                         client_factory=self.model.factory, embedding_client_factory=self.embedder.factory, store_factory=lambda _: self.store)
        with patch.object(self.model, "health", return_value={"model": "other"}), \
                self.assertLogs("uvicorn.error", level="INFO"), TestClient(app):
            self.assertEqual(app.state.startup_connections[0]["status"], "error")
            self.assertIn("Expected model", app.state.startup_connections[0]["error"])
            self.assertEqual(app.state.startup_connections[1]["status"], "ok")

    def test_startup_does_not_write_legacy_log_path(self):
        settings = replace(self.settings, startup_log_path=Path(self.directory.name))
        app = create_app(settings, catalog_loader=lambda _: self.catalog,
                         client_factory=self.model.factory, embedding_client_factory=self.embedder.factory, store_factory=lambda _: self.store)
        with self.assertLogs("uvicorn.error", level="INFO") as console, TestClient(app) as client:
            self.assertEqual(client.get("/health").status_code, 200)
        self.assertTrue(any("classifier OK" in line for line in console.output))
        self.assertTrue(any("embedder OK" in line for line in console.output))
        self.assertTrue(any("Startup connection results saved to PostgreSQL" in line for line in console.output))

    def test_startup_failure_saves_incomplete_report_and_releases_lock(self):
        self.model.offline = True
        response = self.client.post("/analyze", json=self.body)
        self.assertEqual(response.status_code, 502)
        result = response.json()["detail"]["result"]
        self.assertEqual(result["status"], "incomplete_inference")
        run_id = result["run_id"]
        self.assertIn("startup_error.json", self.store.artifacts[run_id])
        self.assertIsNotNone(self.store.runs[run_id]["analysis"])
        self.assertFalse(self.app.state.pipeline.model_lock.locked())

    def test_midrun_failure_stops_without_retry_and_keeps_partial_answers(self):
        self.model.fail_at = 2
        response = self.client.post("/analyze", json=self.body)
        self.assertEqual(response.status_code, 502)
        result = response.json()["detail"]["result"]
        self.assertFalse(result["complete_inference"])
        self.assertIsNone(result["recommended_candidate"])
        self.assertEqual(len(self.model.calls), 2)
        run_id = result["run_id"]
        self.assertEqual(self.store.runs[run_id]["analysis"]["successful_requests"], 1)
        records = [call["record"] for call in self.store.calls[run_id]]
        self.assertIn("response", records[0])
        self.assertIn("error", records[1])
        self.assertFalse(self.app.state.pipeline.model_lock.locked())

    def test_model_health_is_separate_and_uses_short_timeout(self):
        response = self.client.get("/health/model")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "model": ce.MODEL})
        self.assertEqual(self.model.timeout, 5)
        self.model.offline = True
        self.assertEqual(self.client.get("/health/model").status_code, 502)

    def test_saved_result_can_be_recovered_without_rerunning_models(self):
        with self.assertLogs("uvicorn.error", level="INFO") as logs:
            result = self.client.post("/analyze", json=self.body).json()
        model_calls = len(self.model.calls)
        embedding_calls = len(self.embedder.calls)
        response = self.client.get("/results/" + result["run_id"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result)
        self.assertEqual(len(self.model.calls), model_calls)
        self.assertEqual(len(self.embedder.calls), embedding_calls)
        self.assertTrue(any("Analysis started: run_id=" + result["run_id"] in line for line in logs.output))
        self.assertTrue(any("Analysis saved: run_id=" + result["run_id"] in line for line in logs.output))

    def test_saved_legacy_candidate_status_is_renamed_without_rerunning_models(self):
        result = self.client.post("/analyze", json=self.body).json()
        legacy = deepcopy(result)
        battery = next(c for c in legacy["candidates"] if c["code"] == "battery")
        battery["status"] = "supported"
        self.store.runs[result["run_id"]]["result"] = legacy
        model_calls, embedding_calls = len(self.model.calls), len(self.embedder.calls)

        response = self.client.get("/results/" + result["run_id"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result)
        self.assertEqual(battery["status"], "supported")
        self.assertEqual(len(self.model.calls), model_calls)
        self.assertEqual(len(self.embedder.calls), embedding_calls)

    def test_multiple_compatible_candidates_require_clarification(self):
        alternative = deepcopy(self.catalog["positions"][0])
        alternative.update(key="battery_alternative@1", code="battery_alternative")
        self.app.state.pipeline.catalog["positions"].append(alternative)

        response = self.client.post("/analyze", json=self.body)

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["status"], "needs_clarification")
        self.assertIsNone(result["recommended_candidate"])
        self.assertEqual([c["code"] for c in result["candidates"] if c["status"] == "compatible"],
                         ["battery", "battery_alternative"])
        facts = self.store.runs[result["run_id"]]["analysis"]["analysis"]["categorical_facts"]
        self.assertEqual(next(f for f in facts if f["id"] == "battery")["status"], "supported")

    def test_saved_partial_result_can_be_recovered_after_model_failure(self):
        self.model.fail_at = 2
        original = self.client.post("/analyze", json=self.body)
        self.assertEqual(original.status_code, 502)
        result = original.json()["detail"]["result"]
        recovered = self.client.get("/results/" + result["run_id"])
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json(), result)
        self.assertFalse(recovered.json()["complete_inference"])
        self.assertEqual(len(self.model.calls), 2)

    def test_saved_result_rejects_unknown_ids_and_arbitrary_file_paths(self):
        response = self.client.get("/results/20261010T123456000000Z_" + "0" * 32)
        self.assertEqual(response.status_code, 404)
        self.assertIn("not saved yet", response.json()["detail"]["error"])
        for run_id in ("startup_connections.jsonl", "not-a-run", "..%5C..%5C.env", "%2e%2e%2f.env"):
            with self.subTest(run_id=run_id):
                self.assertIn(self.client.get("/results/" + run_id).status_code, (404, 422))
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.embedder.calls, [])

    def test_openapi_documents_requests_responses_and_model_failures(self):
        schema = self.client.get("/openapi.json").json()
        self.assertIn("/preview", schema["paths"])
        self.assertIn("/results/{run_id}", schema["paths"])
        responses = schema["paths"]["/analyze"]["post"]["responses"]
        self.assertTrue({"200", "422", "502", "503"} <= responses.keys())
        self.assertIn("AnalysisResponse", schema["components"]["schemas"])
        self.assertEqual(schema["components"]["schemas"]["Candidate"]["properties"]["status"]["enum"],
                         ["compatible", "uncertain", "rejected"])
        self.assertIn("PreviewResponse", schema["components"]["schemas"])

    def test_weakly_rejected_alternative_does_not_hide_compatible_candidate(self):
        mechanical = deepcopy(self.catalog["positions"][0])
        mechanical.update(key="mechanical@1", code="mechanical", name="Дрель ручная механическая", characteristics=[])
        self.app.state.pipeline.catalog["positions"].append(mechanical)
        qid = "product_" + ce.identity(mechanical["name"])
        self.model.overrides[qid] = ("contradicted", .7492505619293989)
        response = self.client.post("/analyze", json={"text": "Аккумуляторная дрель", "scope": "all"})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["recommended_candidate"], "battery@1")
        self.assertIn("Напряжение аккумулятора", result["clarifying_question"])
        self.assertNotIn("механическая", result["clarifying_question"])
        alternative = next(c for c in result["candidates"] if c["code"] == "mechanical")
        self.assertEqual(alternative["status"], "uncertain")
        self.assertNotIn("missing_required", alternative)
        self.assertEqual(alternative["unmatched_properties"], ["Тип питания"])
        self.assertTrue(result["warnings"])

    def test_compact_result_preserves_conflicts_without_claiming_a_recommendation(self):
        self.model.overrides["mains"] = ("supported", .95)
        response = self.client.post("/analyze", json=self.body)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertIsNone(result["recommended_candidate"])
        self.assertEqual(result["status"], "needs_clarification")
        self.assertTrue(all(c["status"] == "uncertain" for c in result["candidates"]))
        self.assertTrue(any("Тип питания" in reason for c in result["candidates"] for reason in c["reasons"]))
        self.assertFalse(any(property["name"] == "Тип питания" for property in result["properties"]))
        self.assertTrue(any("Тип питания" in warning for warning in result["warnings"]))

    def test_equivalent_battery_values_are_deduplicated_without_hiding_conflicts(self):
        self.app.state.pipeline.catalog["facts"].append(dict(
            id="battery_alias", name="Тип питания", value="От аккумуляторных батарей", unit_code="",
            sources=[dict(position="battery@1", characteristic_code="power", value_ordinal=0)],
        ))
        response = self.client.post("/analyze", json=self.body)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["recommended_candidate"], "battery@1")
        self.assertEqual([p for p in result["properties"] if p["name"] == "Тип питания"],
                         [{"name": "Тип питания", "value": "От аккумулятора"}])
        self.assertEqual(next(c for c in result["candidates"] if c["code"] == "mains")["status"], "rejected")
        run_id = result["run_id"]
        facts = self.store.runs[run_id]["analysis"]["analysis"]["categorical_facts"]
        self.assertTrue(any(f["value"] == "От аккумуляторных батарей" for f in facts))

    def test_numeric_conflict_has_a_readable_reason(self):
        response = self.client.post("/analyze", json={"text": "Аккумуляторная дрель 20 В", "scope": "drills"})
        result = response.json()
        self.assertEqual(result["status"], "no_compatible_shortlist_candidate")
        self.assertIsNone(result["recommended_candidate"])
        self.assertTrue(all(c["status"] == "rejected" for c in result["candidates"]))
        self.assertTrue(all("missing_required" not in c for c in result["candidates"]))
        battery = next(c for c in result["candidates"] if c["code"] == "battery")
        self.assertTrue(any("20 В" in reason and "вне допустимых" in reason for reason in battery["reasons"]))

    def test_numeric_rejection_does_not_promote_a_weak_product_rejection(self):
        qid = "product_" + ce.identity("Дрель ручная электрическая")
        self.model.overrides[qid] = ("contradicted", .75)
        result = self.client.post("/analyze", json={"text": "Аккумуляторная дрель 20 В"}).json()
        battery = next(c for c in result["candidates"] if c["code"] == "battery")
        self.assertEqual(battery["status"], "rejected")
        self.assertTrue(any("20 В" in reason for reason in battery["reasons"]))
        self.assertNotIn("Указанный вид товара не соответствует описанию.", battery["reasons"])

    def test_catalog_cache_and_xml_fallback(self):
        cache = Path(self.directory.name) / "catalog.json"
        cache.write_text(json.dumps(self.catalog))
        with patch("backend.src.service.ce.load_catalog", return_value=self.catalog) as importer:
            self.assertEqual(load_catalog(Settings(catalog_path=cache)), self.catalog)
            importer.assert_not_called()
            cache.unlink()
            settings = Settings(catalog_path=cache, xml_dir=Path(self.directory.name) / "custom-xml")
            self.assertEqual(load_catalog(settings), self.catalog)
            importer.assert_called_once_with(settings.xml_dir)


if __name__ == "__main__":
    unittest.main()
