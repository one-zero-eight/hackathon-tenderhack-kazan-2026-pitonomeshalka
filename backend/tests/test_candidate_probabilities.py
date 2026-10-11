"""Product identity evidence must survive API rendering, persistence and polling."""

from dataclasses import replace
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import Range

from backend.src.app import inference_failure_handler
from backend.src.models import KtruCharacteristic, KtruPosition, KtruValue
from backend.src.retrieval import Retrieval
from backend.src.routes import get_pipeline_service, router
from backend.src.service import InferenceFailure, PipelineService
from backend.src.settings import Settings
from backend.tests.memory_store import MemoryStore
from experiments import classifier_experiments as ce


class CandidateProbabilityTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.model = Mock(base_url="http://fake", timeout=1)
        self.model.health.return_value = {"model": ce.MODEL}
        self.answers = {}
        self.model.infer.side_effect = self.infer
        self.service = PipelineService(
            replace(Settings(), classifier_batch_size=0),
            client_factory=lambda *_: self.model, store=self.store,
        )
        self.addCleanup(self.service.close)
        self.service.retriever = Mock()
        app = FastAPI()
        app.include_router(router)
        app.add_exception_handler(InferenceFailure, inference_failure_handler)
        app.dependency_overrides[get_pipeline_service] = lambda: self.service
        self.client = self.enterContext(TestClient(app))

    def infer(self, body):
        answers = {}
        for qid, question in body["questions"].items():
            choice, probability = self.answers.get(qid, ("span_0", .95))
            answers[qid] = {"choice": choice, "probabilities": {
                key: probability if key == choice else (1 - probability) / (len(question["criteria"]) - 1)
                for key in question["criteria"]
            }}
        return {"response": {"model": ce.MODEL, "answers": answers}, "elapsed_seconds": .01}

    def position(self, code, name, choice, probability, characteristics=None):
        self.answers["product_" + ce.identity(ce.normalize(name))] = (choice, probability)
        return KtruPosition(import_sha256="fixture", code=code, version=1, name=name,
                            characteristics=characteristics or [])

    def retrieve(self, positions):
        self.service.retriever.retrieve.return_value = Retrieval("fixture", positions, [], len(positions), False)

    def test_probabilities_order_across_statuses_and_survive_saved_results_and_polling(self):
        incompatible_voltage = KtruCharacteristic(
            code="voltage", name="Напряжение аккумулятора", actual=True, is_numeric=True,
            choice="one_of", required=True,
            values=[KtruValue(id=1, ordinal=0, okei="222", spans=[Range(1, 2, bounds="[]")])],
        )
        self.retrieve([
            self.position("a", "Слабое совпадение", "unknown", .96),
            self.position("m", "Среднее совпадение", "supported", .9),
            self.position("z", "Сильное совпадение", "supported", .98, [incompatible_voltage]),
            self.position("b", "Среднее совпадение", "supported", .9),
            self.position("zero", "Нулевое совпадение", "contradicted", 1),
        ])
        response = self.client.post("/analyze", json={"text": "Аккумуляторная дрель 18 В"})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        candidates = result["candidates"]
        self.assertEqual([c["code"] for c in candidates], ["z", "b", "m", "a", "zero"])
        self.assertEqual(candidates[0]["status"], "rejected")
        self.assertEqual(candidates[1]["status"], "compatible")
        self.assertEqual(candidates[3]["status"], "uncertain")
        scores = [c["probabilities"]["supported"] for c in candidates]
        self.assertEqual(scores, sorted(scores, reverse=True))
        saved = self.store.runs[result["run_id"]]
        for candidate in candidates:
            raw = next(c for c in saved["analysis"]["analysis"]["candidates"] if c["code"] == candidate["code"])
            self.assertEqual(candidate["choice"], raw["product_relevance"]["choice"])
            self.assertEqual(candidate["probabilities"], raw["product_relevance"]["probabilities"])
            self.assertAlmostEqual(sum(candidate["probabilities"].values()), 1)
        self.assertEqual(self.client.get("/results/" + result["run_id"]).json(), result)
        polled = self.client.get("/analyses/" + result["run_id"]).json()["result"]
        self.assertEqual([c["probabilities"] for c in polled["candidates"]],
                         [c["probabilities"] for c in candidates])
        accepted = self.client.post("/analyses", json={"text": "Аккумуляторная дрель 18 В"})
        self.assertEqual(accepted.status_code, 202)
        self.service.close()
        completed = self.client.get("/analyses/" + accepted.json()["run_id"]).json()
        self.assertEqual(completed["status"], "completed")
        self.assertEqual([c["code"] for c in completed["result"]["candidates"]],
                         [c["code"] for c in candidates])
        self.assertEqual([c["probabilities"] for c in completed["result"]["candidates"]],
                         [c["probabilities"] for c in candidates])

    def test_unanswered_candidates_sort_after_an_answer_with_zero_supported_probability(self):
        self.retrieve([
            self.position("a", "Б неизвестный товар", "supported", .95),
            self.position("z", "А исключённый товар", "contradicted", 1),
        ])
        original_infer = self.infer

        def fail_second(body):
            if self.model.infer.call_count == 2:
                raise RuntimeError("inference timed out")
            return original_infer(body)

        self.model.infer.side_effect = fail_second
        response = self.client.post("/analyze", json={"text": "дрель"})
        self.assertEqual(response.status_code, 502, response.text)
        result = response.json()["detail"]["result"]
        self.assertFalse(result["complete_inference"])
        self.assertEqual([c["code"] for c in result["candidates"]], ["z", "a"])
        self.assertEqual(result["candidates"][0]["probabilities"]["supported"], 0)
        self.assertNotIn("probabilities", result["candidates"][1])
        self.assertNotIn("choice", result["candidates"][1])
        self.assertEqual(self.client.get("/results/" + result["run_id"]).json(), result)

    def test_legacy_saved_results_without_model_evidence_remain_readable(self):
        self.retrieve([self.position("a", "Дрель", "supported", .95)])
        result = self.client.post("/analyze", json={"text": "дрель"}).json()
        for candidate in self.store.runs[result["run_id"]]["result"]["candidates"]:
            candidate.pop("choice")
            candidate.pop("probabilities")
        response = self.client.get("/results/" + result["run_id"])
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("probabilities", response.json()["candidates"][0])

    def test_openapi_exposes_the_product_identity_distribution(self):
        schemas = self.client.get("/openapi.json").json()["components"]["schemas"]
        self.assertTrue({"choice", "probabilities"} <= schemas["Candidate"]["properties"].keys())
        self.assertEqual(set(schemas["CandidateProbabilities"]["required"]),
                         {"supported", "contradicted", "unknown", "conflicting"})


if __name__ == "__main__":
    unittest.main()
