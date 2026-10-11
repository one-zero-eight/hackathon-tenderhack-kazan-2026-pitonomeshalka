"""POST /clarify contract on a fake store: no database, no model calls, no model lock."""

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import unittest

from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import Range

from backend.src.app import create_app
from backend.src.clarify import CLARIFICATION_STATE, build_clarification, initial_candidate_codes
from backend.src.models import KtruCharacteristic, KtruPosition, KtruValue
from backend.src.pipeline import CandidateAssessment, Plan, Report
from backend.src.presentation import analysis_response, with_primary_clarification
from backend.src.retrieval import Retrieval
from backend.src.schemas import AnalysisResponse, Clarification
from backend.tests.memory_store import MemoryStore
from experiments.classifier_experiments import identity
from experiments.config import Settings

RUN_ID = "20261011T120000000000Z_" + "a" * 32
IMPORT_SHA256 = "import-sha"


def split_option(text, children):
    return {"text": text, "spans": None, "okei": None, "issue": None, "children": children}


def splitting_characteristic(name, options):
    return {"code": identity(name), "name": name, "required": True, "is_numeric": False,
            "resolved": False, "observed": False, "options": options}


def result_fixture():
    """A saved needs_clarification result: three live candidates, one rejected."""
    return {
        "run_id": RUN_ID, "status": "needs_clarification", "complete_inference": True,
        "recommended_candidate": None, "requires_review": True, "properties": [],
        "candidates": [
            {"code": "10", "version": "1", "name": "Дрель аккумуляторная", "status": "compatible", "reasons": []},
            {"code": "20", "version": "1", "name": "Дрель сетевая", "status": "uncertain", "reasons": []},
            {"code": "30", "version": "1", "name": "Дрель ручная", "status": "uncertain", "reasons": []},
            {"code": "40", "version": "1", "name": "Перфоратор", "status": "rejected", "reasons": ["Конфликт типа"]},
        ],
        "clarifying_question": "Уточните тип дрели.",
        "warnings": [],
        "detected_families": [{
            "code": "family", "version": "1", "name": "Дрели", "resolved": False,
            "candidate_codes": ["10", "20", "30", "40"],
            "splitting_characteristics": [splitting_characteristic("Питание", [
                split_option("Аккумуляторные и сетевые", ["10", "20"]),
                split_option("Ручные", ["30"]),
            ])],
        }],
    }


def three_round_fixture():
    """Overlapping value domains keep two candidates alive into the manual round."""
    fixture = result_fixture()
    fixture["candidates"] = [candidate for candidate in fixture["candidates"] if candidate["code"] != "30"]
    fixture["detected_families"][0]["splitting_characteristics"] = [
        splitting_characteristic("Питание", [
            split_option("Аккумуляторные", ["10", "20"]),
            split_option("Прочие", ["30"]),
        ]),
        splitting_characteristic("Корпус", [
            split_option("Любой корпус", ["10", "20", "30"]),
            split_option("Только металл", ["10"]),
        ]),
    ]
    return fixture


def card_position(code):
    position = KtruPosition(
        import_sha256=IMPORT_SHA256, code=code, version=1,
        updated=datetime(2026, 1, 15, 10, 30), name="Дрель сетевая",
        status="ACTIVE", applies_from=date(2025, 1, 1), units=["шт"],
        rubrics=["Инструмент"], rubric_codes=["116"], source_file_id=7, source_line=42,
    )
    characteristic = KtruCharacteristic(
        import_sha256=IMPORT_SHA256, position_code=code, code="080",
        name="Питание", is_numeric=False, choice="one_of", required=True, actual=True,
    )
    characteristic.values.extend([
        KtruValue(id=11, ordinal=0, text="От сети", okei="168"),
        KtruValue(id=12, ordinal=1, text=None,
                  spans=[Range(Decimal("3"), Decimal("6"), bounds="[)")], okei="112", value_format="N"),
    ])
    position.characteristics.extend([characteristic])
    return position


def assessment(code, status):
    return CandidateAssessment(position=card_position(code), status=status, product_answer=None,
                               findings=[], missing_required=[], unmatched=[], extras=[], reasons=[])


class FakeUpstream:
    """Lifespan probes accept any health answer; clarification never calls either model."""

    def __init__(self, *args):
        self.args = args

    def health(self):
        return {}


class ClarifyApiTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        # Empty Redis URL keeps the lifespan offline; history is irrelevant to clarification.
        self.app = create_app(Settings(redis_url=""), client_factory=FakeUpstream,
                              embedding_client_factory=FakeUpstream, store_factory=lambda _: self.store)
        self.client = self.enterContext(TestClient(self.app))

    def seed_run(self, result, *, with_result=True, positions=()):
        self.store.begin_run(RUN_ID, {"text": "Дрель"})
        self.store.save_plan(RUN_ID, {"import_sha256": IMPORT_SHA256, "requests": []})
        if with_result:
            self.store.finish_run(RUN_ID, {}, deepcopy(result))
        for position in positions:
            self.store.positions.setdefault(IMPORT_SHA256, {})[position.code] = position
        self.saved_result = deepcopy(self.store.runs[RUN_ID]["result"])

    def first_question(self, result):
        return build_clarification(result, initial_candidate_codes(result), 1)

    def post(self, question_id, option_id, run_id=RUN_ID):
        return self.client.post("/clarify", json={
            "run_id": run_id, "question_id": question_id, "option_id": option_id})

    def assert_result_untouched(self):
        self.assertEqual(self.store.runs[RUN_ID]["result"], self.saved_result)

    def test_state_artifact_name_is_pinned(self):
        self.assertEqual(CLARIFICATION_STATE, "clarification_state.json")

    def test_initial_candidate_codes_are_non_rejected_in_result_order(self):
        result = result_fixture()
        self.assertEqual(initial_candidate_codes(result), ["10", "20", "30"])
        self.assertEqual(initial_candidate_codes({"candidates": []}), [])

    def test_completed_run_first_answer_narrows_and_saves_state(self):
        result = result_fixture()
        self.seed_run(result)
        question = self.first_question(result)
        option = next(item for item in question["options"] if item["candidate_codes"] == ["10", "20"])

        response = self.post(question["question_id"], option["id"])

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["run_id"], RUN_ID)
        self.assertEqual(payload["status"], "needs_clarification")
        self.assertEqual([candidate["code"] for candidate in payload["candidates"]], ["10", "20", "30", "40"])
        self.assertNotIn("final_card", payload)
        self.assertNotIn("suggest_expand", payload)
        following = payload["clarification"]
        expected = Clarification.model_validate(build_clarification(result, ["10", "20"], 2))
        self.assertEqual(following, expected.model_dump(mode="json", exclude_defaults=True))
        self.assertEqual(following["kind"], "product")
        self.assertFalse(following["manual_choice"])
        state = self.store.artifacts[RUN_ID][CLARIFICATION_STATE]
        self.assertEqual(state, {"round": 2, "candidate_codes": ["10", "20"],
                                 "question_id": following["question_id"],
                                 "answers": [{"question_id": question["question_id"], "option_id": option["id"]}]})
        self.assert_result_untouched()

    def test_answer_leaving_one_code_returns_final_card_without_clarification(self):
        result = result_fixture()
        self.seed_run(result, positions=[card_position("30")])
        question = self.first_question(result)
        option = next(item for item in question["options"] if item["candidate_codes"] == ["30"])

        response = self.post(question["question_id"], option["id"])

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("clarification", payload)
        card = payload["final_card"]
        self.assertEqual(card["code"], "30")
        self.assertTrue(card["requires_review"])
        self.assertIn(question["question_id"], card["rationale"])
        self.assertIn(option["id"], card["rationale"])
        state = self.store.artifacts[RUN_ID][CLARIFICATION_STATE]
        self.assertEqual(state["candidate_codes"], ["30"])
        self.assertEqual(state["round"], 1)
        self.assert_result_untouched()

    def test_final_card_characteristic_units_are_the_sorted_okei_set(self):
        result = result_fixture()
        # Round-two product question for ["10", "20"], then pick code 20 with the ranged value.
        self.seed_run(result, positions=[card_position("20")])
        question = self.first_question(result)
        battery = next(item for item in question["options"] if item["candidate_codes"] == ["10", "20"])
        second = self.post(question["question_id"], battery["id"]).json()["clarification"]
        option = next(item for item in second["options"] if item["candidate_codes"] == ["20"])

        payload = self.post(second["question_id"], option["id"]).json()

        characteristic = payload["final_card"]["characteristics"][0]
        self.assertEqual(characteristic["units"], ["112", "168"])
        self.assertTrue(characteristic["required"])
        self.assertEqual([value["id"] for value in characteristic["values"]], [11, 12])
        self.assertEqual(characteristic["values"][1]["spans"],
                         [{"lower": "3", "upper": "6", "bounds": "[)", "empty": False}])

    def test_three_rounds_reach_manual_choice(self):
        result = three_round_fixture()
        self.seed_run(result)
        first = self.first_question(result)
        first_option = next(item for item in first["options"] if item["candidate_codes"] == ["10", "20"])
        second = self.post(first["question_id"], first_option["id"]).json()["clarification"]
        self.assertEqual(second["kind"], "characteristic")
        second_option = next(item for item in second["options"] if item["candidate_codes"] == ["10", "20"])

        third = self.post(second["question_id"], second_option["id"]).json()["clarification"]

        self.assertEqual(third["kind"], "product")
        self.assertTrue(third["manual_choice"])
        self.assertEqual([item["candidate_codes"] for item in third["options"]], [["10"], ["20"], []])
        state = self.store.artifacts[RUN_ID][CLARIFICATION_STATE]
        self.assertEqual(state["round"], 3)
        self.assertEqual(state["candidate_codes"], ["10", "20"])

    def test_none_option_suggests_expand_without_a_new_question(self):
        result = result_fixture()
        self.seed_run(result)
        question = self.first_question(result)
        none_option = next(item for item in question["options"] if item["suggest_expand"])

        response = self.post(question["question_id"], none_option["id"])

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["suggest_expand"])
        self.assertNotIn("clarification", payload)
        self.assertNotIn("final_card", payload)
        state = self.store.artifacts[RUN_ID][CLARIFICATION_STATE]
        self.assertEqual(state["answers"], [{"question_id": question["question_id"], "option_id": none_option["id"]}])
        self.assertEqual(state["candidate_codes"], [])
        # The answered question is closed: any replay is stale and writes nothing.
        replay = self.post(question["question_id"], none_option["id"])
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(len(state["answers"]), 1)
        self.assert_result_untouched()

    def test_stale_question_returns_409_and_writes_nothing(self):
        result = result_fixture()
        self.seed_run(result)
        stale = build_clarification(result, ["10", "20"], 2)["question_id"]

        response = self.post(stale, "option_whatever")

        self.assertEqual(response.status_code, 409)
        self.assertIn("error", response.json()["detail"])
        self.assertEqual(self.store.artifacts.get(RUN_ID, {}), {})
        self.assert_result_untouched()

    def test_unknown_option_returns_409_and_writes_nothing(self):
        result = result_fixture()
        self.seed_run(result)
        question = self.first_question(result)

        response = self.post(question["question_id"], "option_missing")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.store.artifacts.get(RUN_ID, {}), {})
        self.assert_result_untouched()

    def test_unknown_run_or_missing_result_returns_404(self):
        result = result_fixture()
        self.seed_run(result)
        missing_id = "20261011T120000000000Z_" + "b" * 32

        unknown = self.post("question", "option", run_id=missing_id)
        self.seed_run(result, with_result=False)
        unanswered = self.post("question", "option")

        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(unanswered.status_code, 404)
        for response in (unknown, unanswered):
            self.assertIn("error", response.json()["detail"])

    def test_invalid_bodies_fail_pydantic_validation(self):
        self.seed_run(result_fixture())
        malformed = [
            {"run_id": "not-a-run-id", "question_id": "q", "option_id": "o"},
            {"run_id": RUN_ID, "question_id": "q"},
            {"run_id": RUN_ID, "question_id": "q", "option_id": "  "},
            {"run_id": RUN_ID, "question_id": "q", "option_id": "o", "extra": 1},
        ]
        for body in malformed:
            with self.subTest(body=body):
                response = self.client.post("/clarify", json=body)
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.store.artifacts.get(RUN_ID, {}), {})

    def test_clarify_never_takes_the_model_lock(self):
        result = result_fixture()
        self.seed_run(result, positions=[card_position("30")])
        question = self.first_question(result)
        option = next(item for item in question["options"] if item["candidate_codes"] == ["30"])

        with self.app.state.pipeline.model_lock:
            response = self.post(question["question_id"], option["id"])

        self.assertEqual(response.status_code, 200)
        self.assertIn("final_card", response.json())


class AnalyzeEnrichmentTests(unittest.TestCase):
    def test_candidates_keep_the_report_order_without_status_sorting(self):
        report = Report(
            plan=Plan(text="Дрель", retrieval=Retrieval(IMPORT_SHA256, [], [], 0, False),
                      hypotheses=[], bindings=[], spans=[], jobs=[]),
            status="needs_clarification", complete_inference=True, recommended=None,
            # Retrieval order: uncertain first, then compatible, then rejected.
            candidates=[assessment("20", "uncertain"), assessment("10", "supported"),
                        assessment("40", "rejected")],
            properties=[], clarifying_question=None, warnings=[], answers={}, threshold=0.5,
        )

        response = analysis_response(report, RUN_ID)

        self.assertEqual([candidate.code for candidate in response.candidates], ["20", "10", "40"])
        self.assertEqual([candidate.status for candidate in response.candidates],
                         ["uncertain", "compatible", "rejected"])

    def test_needs_clarification_response_gains_the_round_one_clarification(self):
        result = result_fixture()
        snapshot = deepcopy(result)

        response = with_primary_clarification(result)

        self.assertEqual(result, snapshot)
        self.assertEqual(response.clarification.model_dump(), build_clarification(result, ["10", "20", "30"], 1))
        self.assertFalse(response.clarification.manual_choice)
        self.assertIsNone(response.final_card)
        self.assertFalse(response.suggest_expand)
        self.assertEqual([candidate.code for candidate in response.candidates], ["10", "20", "30", "40"])
        plain = AnalysisResponse.model_validate(result)
        self.assertEqual(plain.model_dump(mode="json", exclude_defaults=True), result)

    def test_unambiguous_response_stays_plain(self):
        result = result_fixture()
        result["status"] = "ready_for_review"
        result["candidates"] = [dict(result["candidates"][0])]
        result["detected_families"] = []
        result["clarifying_question"] = None

        response = with_primary_clarification(result)

        self.assertIsNone(response.clarification)
        self.assertIsNone(response.final_card)
        self.assertFalse(response.suggest_expand)
        self.assertFalse(response.manual_choice)

    def test_legacy_candidate_status_still_normalizes(self):
        result = result_fixture()
        result["candidates"][0]["status"] = "supported"

        response = AnalysisResponse.model_validate(result)

        self.assertEqual(response.candidates[0].status, "compatible")


if __name__ == "__main__":
    unittest.main()
