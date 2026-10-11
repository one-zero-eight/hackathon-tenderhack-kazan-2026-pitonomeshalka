"""Question-budget regressions against the current relational pipeline and API."""

from dataclasses import replace
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import Range

from backend.src import pipeline
from backend.src.app import inference_failure_handler, invalid_plan_handler
from backend.src.models import KtruCharacteristic, KtruPosition, KtruValue
from backend.src.retrieval import Retrieval
from backend.src.routes import get_pipeline_service, router
from backend.src.service import InferenceFailure, InvalidPlan, PipelineService
from backend.src.settings import Settings
from backend.tests.memory_store import MemoryStore


TEXT = "Аккумуляторная дрель 18 В с реверсом, без ударного режима"


def position(code, facts=18):
    chars = [KtruCharacteristic(
        code=f"property_{index}", name=f"Характеристика {code} {index}", actual=True,
        is_numeric=False, choice="one_of", required=False,
        values=[KtruValue(id=index, ordinal=0, text="Да", okei=None, spans=[])],
    ) for index in range(facts)]
    chars.append(KtruCharacteristic(
        code="voltage", name="Напряжение аккумулятора", actual=True, is_numeric=True,
        choice="one_of", required=True,
        values=[KtruValue(id=1000, ordinal=0, text=None, okei="222", spans=[Range(12, 20, bounds="[]")])],
    ))
    return KtruPosition(import_sha256="fixture", code=code, version=1,
                        name="Дрель ручная электрическая", characteristics=chars)


def retrieval(positions, families=None):
    return Retrieval("fixture", positions,
                     [{"code": p.code, "score": 1 - index * .01} for index, p in enumerate(positions)],
                     len(positions), False, details={"method": "lexical"}, families=families or [])


def answers_for(plan):
    return [dict(id=job.id, response={"answers": {
        qid: {"choice": "span_0" if job.experiment == "pipeline_numeric" else
              "supported" if job.experiment == "pipeline_product" else "unknown",
              "probabilities": {"span_0": .95, "supported": .95, "unknown": .95}}
        for qid in job.body["questions"]}}) for job in plan.jobs]


class BudgetPlanTests(unittest.TestCase):
    def test_145_questions_retains_seven_ranked_candidates_at_128(self):
        found = retrieval([position(str(i), 18 if i < 7 else 17) for i in range(8)])
        plan = pipeline.prepare(found, TEXT)
        self.assertEqual(plan.question_count, 128)
        self.assertEqual([p.code for p in plan.retrieval.positions], list(map(str, range(7))))
        self.assertEqual([hit["code"] for hit in plan.retrieval.evidence], list(map(str, range(7))))
        self.assertEqual(plan.retrieval.details["question_budget"]["original_questions"], 145)
        self.assertEqual(plan.skipped_question_ids, [])
        report = pipeline.analyze(plan, answers_for(plan))
        self.assertTrue(report.complete_inference)
        self.assertTrue(any("с 8 до 7" in warning for warning in report.warnings))
        # Planning must not mutate the cached retrieval or ORM objects.
        self.assertEqual(len(found.positions), 8)
        self.assertFalse(found.truncated)
        self.assertNotIn("question_budget", found.details)
        self.assertEqual(len(found.positions[-1].characteristics), 18)

    def test_exact_budget_keeps_all_candidates_and_the_original_plan(self):
        found = retrieval([position("a", 3)])
        plan = pipeline.prepare(found, TEXT, max_questions=5)
        self.assertEqual(plan.question_count, 5)
        self.assertIs(plan.retrieval, found)
        self.assertEqual(pipeline.budget_warnings(plan), [])

    def test_single_oversized_candidate_preserves_numeric_checks_and_uncertainty(self):
        plan = pipeline.prepare(retrieval([position("a", 143)]), TEXT)
        self.assertEqual(plan.question_count, 128)
        self.assertEqual(len(plan.skipped_question_ids), 17)
        self.assertEqual([job.experiment for job in plan.jobs[:2]],
                         ["pipeline_product", "pipeline_numeric"])
        report = pipeline.analyze(plan, answers_for(plan))
        self.assertEqual(report.status, "incomplete_inference")
        self.assertFalse(report.complete_inference)
        self.assertIsNone(report.recommended)
        self.assertEqual(report.candidates[0].status, "uncertain")
        self.assertIn(("Напряжение аккумулятора", "18 В"), report.properties)
        self.assertEqual(sum("лимита" in f.reason for f in report.candidates[0].findings), 17)
        self.assertEqual(plan.snapshot()["skipped_question_ids"], plan.skipped_question_ids)

    def test_one_question_budget_returns_product_evidence_without_certifying_candidate(self):
        plan = pipeline.prepare(retrieval([position("a", 1), position("b", 1)]), TEXT, max_questions=1)
        self.assertEqual(len(plan.retrieval.positions), 1)
        self.assertEqual(plan.question_count, 1)
        report = pipeline.analyze(plan, answers_for(plan))
        self.assertEqual(report.candidates[0].status, "uncertain")
        self.assertFalse(report.complete_inference)
        self.assertIsNone(report.recommended)

    def test_missing_answers_are_still_an_inference_failure_after_narrowing(self):
        plan = pipeline.prepare(retrieval([position("a", 3), position("b", 3)]), TEXT, max_questions=5)
        report = pipeline.analyze(plan, [])
        self.assertFalse(report.complete_inference)
        self.assertEqual(report.status, "incomplete_inference")

    def test_retained_family_keeps_unretrieved_sibling_domains(self):
        first, last = position("a", 0), position("b", 30)
        first.parent_code, first.parent_version = "parent_a", 1
        last.parent_code, last.parent_version = "parent_b", 1
        family = {
            "code": "parent_a", "version": 1, "name": first.name,
            "children": [{"code": "a", "name": first.name}, {"code": "hidden", "name": first.name}],
            "splitting_characteristics": [{
                "code": "power", "name": "Тип питания", "name_key": "тип питания", "required": True,
                "is_numeric": False, "variants": [{
                    "is_numeric": False, "choice": "one_of", "domain": power, "children": [code],
                    "values": [{"text": power, "issue": None, "okei": None, "spans": []}],
                } for code, power in (("a", "От аккумулятора"), ("hidden", "От сети"))],
            }],
        }
        other_family = {"code": "parent_b", "version": 1, "name": last.name,
                        "children": [{"code": "b", "name": last.name}], "splitting_characteristics": []}
        plan = pipeline.prepare(retrieval([first, last], [family, other_family]), TEXT, max_questions=4)
        self.assertEqual(plan.retrieval.families, [family])
        report = pipeline.analyze(plan, answers_for(plan))
        self.assertTrue(report.complete_inference)
        self.assertEqual(report.families[0]["candidate_codes"], ["a", "hidden"])
        self.assertFalse(report.families[0]["resolved"])
        self.assertIsNone(report.recommended)

    def test_empty_retrieval_remains_a_miss(self):
        plan = pipeline.prepare(retrieval([]), TEXT, max_questions=1)
        self.assertEqual(plan.question_count, 0)
        self.assertEqual(pipeline.analyze(plan, []).status, "retrieval_miss")

    def test_partial_categorical_domain_cannot_reject_or_resolve_a_family(self):
        child = position("a", 0)
        child.parent_code, child.parent_version = "parent", 1
        child.characteristics.append(KtruCharacteristic(
            code="power", name="Тип питания", actual=True, is_numeric=False, choice="one_of", required=True,
            values=[KtruValue(id=2000, ordinal=0, text="От аккумулятора", okei=None, spans=[])],
        ))
        family = {
            "code": "parent", "version": 1, "name": child.name,
            "children": [{"code": "a", "name": child.name}, {"code": "hidden", "name": child.name}],
            "splitting_characteristics": [{
                "code": "power", "name": "Тип питания", "name_key": "тип питания", "required": True,
                "is_numeric": False, "variants": [{
                    "is_numeric": False, "choice": "one_of", "domain": power, "children": [code],
                    "values": [{"text": power, "issue": None, "okei": None, "spans": []}],
                } for code, power in (("a", "От аккумулятора"), ("hidden", "От сети"))],
            }],
        }
        plan = pipeline.prepare(retrieval([child], [family]), TEXT, max_questions=3)
        self.assertEqual(len(plan.skipped_question_ids), 1)
        records = answers_for(plan)
        for job, record in zip(plan.jobs, records):
            if job.experiment == "pipeline_facts":
                for answer in record["response"]["answers"].values():
                    answer.update(choice="supported")
        report = pipeline.analyze(plan, records)
        self.assertEqual(report.candidates[0].status, "uncertain")
        self.assertIn(child.characteristics[-1], report.candidates[0].missing_required)
        self.assertEqual(report.families[0]["candidate_codes"], ["a", "hidden"])
        self.assertFalse(report.families[0]["resolved"])
        self.assertFalse(report.complete_inference)

    def test_invalid_budget_and_import_are_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            pipeline.prepare(retrieval([position("a")]), TEXT, max_questions=0)
        other = position("other")
        other.import_sha256 = "wrong_import"
        with self.assertRaisesRegex(ValueError, "selected import"):
            pipeline.prepare(retrieval([other]), TEXT)


class BudgetApiTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.model = Mock(base_url="http://fake", timeout=1)
        self.model.health.return_value = {"model": "jiwo-4b"}

        def infer(body):
            answers = {}
            for qid, question in body["questions"].items():
                choices = question["criteria"]
                choice = "span_0" if "span_0" in choices else "unknown"
                if "product_" in qid:
                    choice = "supported"
                answers[qid] = {"choice": choice, "probabilities": {
                    key: .95 if key == choice else .05 / (len(choices) - 1) for key in choices}}
            return {"response": {"answers": answers}, "elapsed_seconds": .01}

        self.model.infer.side_effect = infer
        settings = replace(Settings(), max_questions=128, classifier_batch_size=16)
        self.service = PipelineService(settings, client_factory=lambda *_: self.model, store=self.store)
        self.service.retriever = Mock()
        app = FastAPI()
        app.include_router(router)
        app.add_exception_handler(InferenceFailure, inference_failure_handler)
        app.add_exception_handler(InvalidPlan, invalid_plan_handler)
        app.dependency_overrides[get_pipeline_service] = lambda: self.service
        self.client = self.enterContext(TestClient(app))

    def test_preview_and_analysis_share_the_capped_plan_and_save_budget_evidence(self):
        self.service.retriever.retrieve.return_value = retrieval(
            [position(str(i), 18 if i < 7 else 17) for i in range(8)])
        preview = self.client.post("/preview", json={"text": TEXT})
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["planned_questions"], 128)
        self.assertEqual(preview.json()["planned_requests"], 9)
        self.assertEqual(len(preview.json()["candidates"]), 7)
        self.assertTrue(preview.json()["warnings"])
        self.model.infer.assert_not_called()
        result = self.client.post("/analyze", json={"text": TEXT})
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertTrue(body["complete_inference"])
        self.assertEqual({c["code"] for c in body["candidates"]},
                         {c["code"] for c in preview.json()["candidates"]})
        self.assertEqual(sum(len(call.args[0]["questions"]) for call in self.model.infer.call_args_list), 128)
        self.assertEqual(self.model.infer.call_count, preview.json()["planned_requests"])
        self.assertTrue(all(len(call.args[0]["questions"]) <= 16 for call in self.model.infer.call_args_list))
        saved = self.store.runs[body["run_id"]]
        self.assertEqual(saved["analysis"]["analysis"]["retrieval"]["question_budget"]["original_questions"], 145)
        self.assertEqual(self.client.get("/results/" + body["run_id"]).json(), body)

    def test_huge_single_candidate_returns_saved_partial_result_at_200(self):
        self.service.retriever.retrieve.return_value = retrieval([position("a", 143)])
        response = self.client.post("/analyze", json={"text": TEXT})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["complete_inference"])
        self.assertEqual(body["status"], "incomplete_inference")
        self.assertIsNone(body["recommended_candidate"])
        self.assertEqual(body["candidates"][0]["status"], "uncertain")
        self.assertEqual(sum(len(c.args[0]["questions"]) for c in self.model.infer.call_args_list), 128)

    def test_normal_preview_keeps_its_existing_response_shape(self):
        self.service.retriever.retrieve.return_value = retrieval([position("a", 1)])
        response = self.client.post("/preview", json={"text": TEXT})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(set(response.json()), {"planned_requests", "planned_questions", "candidates"})

    def test_model_failure_after_reduction_still_returns_502_with_saved_partial_result(self):
        self.service.retriever.retrieve.return_value = retrieval([position("a", 143)])
        self.model.infer.side_effect = RuntimeError("inference timed out")
        response = self.client.post("/analyze", json={"text": TEXT})
        self.assertEqual(response.status_code, 502, response.text)
        self.assertFalse(response.json()["detail"]["result"]["complete_inference"])
        self.assertEqual(self.model.infer.call_count, 1)


if __name__ == "__main__":
    unittest.main()
