from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.src.app import create_app
from backend.src.service import load_catalog
from backend.src.settings import Settings
from experiments import nimble_experiments as ne


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
        self.base_url = "http://fake"
        self.timeout = 1

    def factory(self, base_url, timeout):
        self.base_url, self.timeout = base_url, timeout
        return self

    def health(self):
        self.health_calls += 1
        if self.offline:
            raise RuntimeError("model unavailable")
        return dict(model=ne.MODEL)

    def infer(self, body):
        self.calls.append(body)
        if len(self.calls) == self.fail_at:
            raise RuntimeError("inference timed out")
        answers = {}
        for qid, question in body["questions"].items():
            choices = question["criteria"]
            choice = "span_0" if qid == "measurement" else "contradicted" if qid == "mains" else "supported"
            answers[qid] = dict(choice=choice, probabilities={
                key: .95 if key == choice else .05 / (len(choices) - 1) for key in choices
            })
        return dict(request=body, response=dict(model=ne.MODEL, answers=answers), elapsed_seconds=.01)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = Settings(results_dir=Path(self.directory.name) / "runs")
        self.model = FakeModel()
        self.catalog = catalog_fixture()
        self.load_count = 0

        def loader(settings):
            self.load_count += 1
            return deepcopy(self.catalog)

        self.app = create_app(self.settings, catalog_loader=loader, client_factory=self.model.factory)
        self.client = self.enterContext(TestClient(self.app))
        self.body = dict(text="  Аккумуляторная дрель 0,018 кВ.", scope="drills")

    def test_health_loads_catalog_once_and_does_not_probe_model(self):
        for _ in range(2):
            response = self.client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["catalog_positions"], 2)
            self.assertEqual(response.json()["model_readiness"], "not_checked")
        self.assertEqual(self.load_count, 1)
        self.assertEqual(self.model.health_calls, 0)

    def test_preview_preserves_offsets_and_never_calls_model_or_writes(self):
        response = self.client.post("/preview", json=self.body)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["mode"], "preview")
        self.assertEqual(result["planned_requests"], 3)
        self.assertEqual(result["planned_questions"], 4)
        self.assertEqual(result["analysis"]["status"], "incomplete_inference")
        span = result["analysis"]["unbound_measurements"][0]
        self.assertEqual(self.body["text"][span["start"]:span["end"]], span["raw"])
        self.assertEqual(self.model.health_calls, 0)
        self.assertEqual(self.model.calls, [])
        self.assertFalse(self.settings.results_dir.exists())

    def test_analysis_reuses_numeric_rules_extras_and_saves_evidence(self):
        body = dict(self.body, extras=[dict(name="Цвет", value="Синий")])
        response = self.client.post("/analyze", json=body)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["successful_requests"], 3)
        self.assertTrue(result["analysis"]["complete_inference"])
        self.assertEqual(result["analysis"]["provisional_candidate"], "battery")
        self.assertIsNone(result["analysis"]["final_code"])
        battery = next(c for c in result["analysis"]["candidates"] if c["code"] == "battery")
        self.assertEqual(battery["numeric_checks"][0]["status"], "matched")
        self.assertEqual(battery["numeric_checks"][0]["span"]["value"], "18.000")
        self.assertEqual(battery["extra_characteristics"][0]["action"], "do_not_add")
        self.assertEqual(battery["extra_characteristics"][0]["origin"], "user_supplied")
        run = self.settings.results_dir / result["run_id"]
        self.assertEqual(json.loads((run / "analysis.json").read_text()), result)
        self.assertEqual(len((run / "requests.jsonl").read_text().splitlines()), 3)
        self.assertEqual(json.loads((run / "manifest.json").read_text())["catalog_sha256"], result["catalog_sha256"])

    def test_missing_required_information_remains_visible(self):
        response = self.client.post("/analyze", json=dict(text="Аккумуляторная дрель", scope="drills"))
        self.assertEqual(response.status_code, 200)
        analysis = response.json()["analysis"]
        battery = next(c for c in analysis["candidates"] if c["code"] == "battery")
        self.assertEqual(battery["missing_required"][0]["name"], "Напряжение аккумулятора")
        self.assertIn("Напряжение аккумулятора", analysis["clarifying_question"])

    def test_retrieval_miss_does_not_require_model(self):
        self.model.offline = True
        response = self.client.post("/analyze", json=dict(text="Несуществующий продукт"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["analysis"]["status"], "retrieval_miss")
        self.assertEqual(self.model.health_calls, 0)
        self.assertEqual(self.model.calls, [])

    def test_input_validation_rejects_invalid_and_server_only_fields(self):
        for changes in (dict(text=" \t"), dict(scope="other"), dict(top_k=0), dict(top_k=33),
                        dict(chunk_size=9), dict(threshold=1.1), dict(base_url="http://other"),
                        dict(extras=[dict(name=" ", value="blue")])):
            with self.subTest(changes=changes):
                response = self.client.post("/analyze", json=dict(self.body, **changes))
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.model.health_calls, 0)

    def test_question_budget_fails_before_model_or_disk(self):
        app = create_app(Settings(results_dir=self.settings.results_dir, max_questions=1),
                         catalog_loader=lambda _: self.catalog, client_factory=self.model.factory)
        with TestClient(app) as client:
            response = client.post("/analyze", json=self.body)
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"][0]
        self.assertEqual(detail["loc"], ["body"])
        self.assertIn("BACKEND_MAX_QUESTIONS", detail["msg"])
        self.assertEqual(self.model.health_calls, 0)
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
        self.assertEqual(self.model.health_calls, 0)

    def test_startup_failure_saves_incomplete_report_and_releases_lock(self):
        self.model.offline = True
        response = self.client.post("/analyze", json=self.body)
        self.assertEqual(response.status_code, 502)
        result = response.json()["detail"]["result"]
        self.assertEqual(result["analysis"]["status"], "incomplete_inference")
        run = self.settings.results_dir / result["run_id"]
        self.assertTrue((run / "startup_error.json").exists())
        self.assertTrue((run / "analysis.json").exists())
        self.assertFalse(self.app.state.pipeline.model_lock.locked())

    def test_midrun_failure_stops_without_retry_and_keeps_partial_answers(self):
        self.model.fail_at = 2
        response = self.client.post("/analyze", json=self.body)
        self.assertEqual(response.status_code, 502)
        result = response.json()["detail"]["result"]
        self.assertEqual(result["successful_requests"], 1)
        self.assertFalse(result["analysis"]["complete_inference"])
        self.assertIsNone(result["analysis"]["provisional_candidate"])
        self.assertEqual(len(self.model.calls), 2)
        run = self.settings.results_dir / result["run_id"]
        records = [json.loads(line) for line in (run / "requests.jsonl").read_text().splitlines()]
        self.assertIn("response", records[0])
        self.assertIn("error", records[1])
        self.assertFalse(self.app.state.pipeline.model_lock.locked())

    def test_model_health_is_separate_and_uses_short_timeout(self):
        response = self.client.get("/health/model")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["upstream"]["model"], ne.MODEL)
        self.assertEqual(self.model.timeout, 5)
        self.model.offline = True
        self.assertEqual(self.client.get("/health/model").status_code, 502)

    def test_openapi_documents_requests_responses_and_model_failures(self):
        schema = self.client.get("/openapi.json").json()
        self.assertIn("/preview", schema["paths"])
        responses = schema["paths"]["/analyze"]["post"]["responses"]
        self.assertTrue({"200", "422", "502", "503"} <= responses.keys())
        self.assertIn("AnalysisReport", schema["components"]["schemas"])

    def test_catalog_cache_and_xml_fallback(self):
        cache = Path(self.directory.name) / "catalog.json"
        cache.write_text(json.dumps(self.catalog))
        with patch("backend.src.service.ne.load_catalog", return_value=self.catalog) as importer:
            self.assertEqual(load_catalog(Settings(catalog_path=cache)), self.catalog)
            importer.assert_not_called()
            cache.unlink()
            self.assertEqual(load_catalog(Settings(catalog_path=cache)), self.catalog)
            importer.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
