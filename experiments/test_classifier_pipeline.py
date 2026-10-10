"""Offline regression cases for retrieval, constraints, replay and diagnostics."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import classifier_experiments as ce
import classifier_pipeline as pipeline


def distribution(choice, choices, probability=.95):
    return {"choice": choice, "probabilities": {k: probability if k == choice else (1 - probability) / (len(choices) - 1) for k in choices}}


def catalog_fixture():
    positions = []
    facts = []
    for key, power, no_new in (("battery", "От аккумулятора", "true"), ("mains", "От сети", "false")):
        position = {"key": key + "@1", "code": key, "version": "1", "name": "Дрель ручная электрическая",
                    "domains": ["tools"], "source": "fixture.xml", "no_new_features": no_new,
                    "characteristics": [{"code": key + "_power", "name": "Тип питания", "type": "1", "kind": "1", "required": True,
                                          "values": [{"text": power, "unit_code": ""}]}]}
        if key == "battery":
            position["characteristics"].append({"code": "voltage", "name": "Напряжение аккумулятора", "type": "2", "kind": "2", "required": True,
                "values": [{"text": "", "unit_code": "222", "exact": [], "ranges": [{"min": "12", "max": "20", "minMathNotation": "greaterOrEqual", "maxMathNotation": "less"}]}]})
        positions.append(position)
        facts.append({"id": key, "name": "Тип питания", "value": power, "unit_code": "",
                      "sources": [{"position": position["key"], "characteristic_code": key + "_power", "value_ordinal": 0}]})
    return {"positions": positions, "facts": facts}


def answer_jobs(plan, power="supported", numeric="span_0"):
    records = []
    for job in plan["jobs"]:
        answers = {}
        for qid, question in job["body"]["questions"].items():
            if job["experiment"] == "pipeline_product":
                choice = "supported"
            elif job["experiment"] == "pipeline_facts":
                choice = power if qid == "battery" else "contradicted"
            else:
                choice = numeric
            answers[qid] = distribution(choice, question["criteria"])
        records.append(dict({k: v for k, v in job.items() if k != "body"}, request=job["body"],
                            response={"model": ce.MODEL, "answers": answers}, elapsed_seconds=.1))
    return records


class ConstraintTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog_fixture()

    def test_unknown_never_eliminates_and_asks_distinguishing_question(self):
        plan = pipeline.prepare(self.catalog, "Нужна дрель.")
        records = answer_jobs(plan, power="unknown")
        for record in records:
            if record["experiment"] == "pipeline_product":
                continue
            for qid, answer in record["response"]["answers"].items():
                record["response"]["answers"][qid] = distribution("unknown", ce.STATUSES)
        report = pipeline.analyze(plan, records)
        self.assertEqual(sum(c["compatible"] for c in report["candidates"]), 2)
        self.assertIn("Тип питания", report["clarifying_question"])
        self.assertIsNone(report["final_code"])

    def test_voltage_normalizes_and_required_missing_prevents_final_code(self):
        plan = pipeline.prepare(self.catalog, "Аккумуляторная дрель 0,018 кВ.")
        records = answer_jobs(plan)
        report = pipeline.analyze(plan, records)
        battery = next(c for c in report["candidates"] if c["code"] == "battery")
        self.assertEqual(report["provisional_candidate"], "battery")
        self.assertEqual(battery["numeric_checks"][0]["status"], "matched")
        self.assertEqual(battery["numeric_checks"][0]["span"]["value"], "18.000")
        self.assertIsNone(report["final_code"])
        missing_plan = pipeline.prepare(self.catalog, "Аккумуляторная дрель.")
        missing = pipeline.analyze(missing_plan, answer_jobs(missing_plan))
        self.assertIn("Напряжение аккумулятора", missing["clarifying_question"])

    def test_charger_only_voltage_stays_unbound(self):
        plan = pipeline.prepare(self.catalog, "Дрель с аккумулятором; зарядник от сети 220 В.")
        report = pipeline.analyze(plan, answer_jobs(plan, numeric="unknown"))
        self.assertEqual(report["numeric_bindings"], [])
        self.assertEqual(report["unbound_measurements"][0]["raw"], "220 В")
        self.assertTrue(next(c for c in report["candidates"] if c["code"] == "battery")["compatible"])

    def test_numeric_boundary_is_open_and_outside_value_excludes(self):
        entry = self.catalog["positions"][0]["characteristics"][1]["values"][0]
        self.assertTrue(pipeline.numeric_rule("12", entry))
        self.assertTrue(pipeline.numeric_rule("19.999", entry))
        self.assertFalse(pipeline.numeric_rule("20", entry))
        self.assertFalse(pipeline.numeric_rule("11.999", entry))
        broken = deepcopy(entry)
        broken["ranges"][0]["maxMathNotation"] = ""
        self.assertIsNone(pipeline.numeric_rule("18", broken))
        plan = pipeline.prepare(self.catalog, "Аккумуляторная дрель 20 В.")
        report = pipeline.analyze(plan, answer_jobs(plan))
        self.assertFalse(any(c["compatible"] for c in report["candidates"]))

    def test_signed_bounds_and_ranges_are_not_point_measurements(self):
        for text in ("Дрель -18 В.", "Дрель 12–18 В.", "Дрель не менее 18 В.", "Дрель от 12 до 18 В."):
            with self.subTest(text=text):
                plan = pipeline.prepare(self.catalog, text)
                self.assertFalse(any(j["experiment"] == "pipeline_numeric" for j in plan["jobs"]))
                self.assertTrue(plan["spans"])

    def test_conflicting_positive_facts_remain_uncertain(self):
        plan = pipeline.prepare(self.catalog, "Дрель от сети и аккумулятора одновременно.")
        records = answer_jobs(plan)
        for record in records:
            for qid in record["response"]["answers"]:
                record["response"]["answers"][qid] = distribution("supported", ce.STATUSES)
        report = pipeline.analyze(plan, records)
        self.assertTrue(all(c["compatible"] and c["uncertain"] for c in report["candidates"]))
        self.assertIsNone(report["provisional_candidate"])

    def test_extras_policy_preserves_raw_field_and_does_not_claim_mapping(self):
        plan = pipeline.prepare(self.catalog, "Нужна дрель.")
        report = pipeline.analyze(plan, [], confirmed_extras=[{"name": "Цвет", "value": "Синий"}])
        actions = {c["code"]: c["extra_characteristics"][0]["action"] for c in report["candidates"]}
        self.assertEqual(actions, {"battery": "do_not_add", "mains": "review_before_add"})

    def test_incomplete_scan_cannot_create_provisional_code(self):
        plan = pipeline.prepare(self.catalog, "Аккумуляторная дрель 18 В.")
        records = answer_jobs(plan)[:-1]
        report = pipeline.analyze(plan, records)
        self.assertEqual(report["status"], "incomplete_inference")
        self.assertIsNone(report["provisional_candidate"])

    def test_properties_and_accessories_do_not_drive_object_retrieval(self):
        catalog = catalog_fixture()
        stamp = deepcopy(catalog["positions"][0])
        stamp.update(key="stamp@1", code="stamp", name="Клеймо ударное")
        catalog["positions"].append(stamp)
        retrieval = pipeline.retrieve(catalog, "Нужна аккумуляторная дрель с реверсом, без ударного режима.")
        self.assertNotIn("stamp", [p["code"] for p in retrieval["positions"]])
        self.assertFalse(pipeline.prepare(catalog_fixture(), "Нужен аккумулятор для дрели.")["jobs"])

    def test_product_name_must_be_supported_before_provisional_selection(self):
        plan = pipeline.prepare(self.catalog, "Аккумуляторная дрель 18 В.")
        records = answer_jobs(plan)
        records[0]["response"]["answers"][records[0]["id"]] = distribution("unknown", ce.STATUSES)
        report = pipeline.analyze(plan, records)
        self.assertIsNone(report["provisional_candidate"])
        self.assertIn("вид самого товара", report["clarifying_question"])

    def test_uncertain_product_alternative_does_not_block_compatible_selection(self):
        mechanical = deepcopy(self.catalog["positions"][0])
        mechanical.update(key="mechanical@1", code="mechanical", name="Дрель ручная механическая", characteristics=[])
        self.catalog["positions"].append(mechanical)
        plan = pipeline.prepare(self.catalog, "Аккумуляторная дрель")
        records = answer_jobs(plan)
        for record in records:
            if record.get("product_name") == mechanical["name"]:
                record["response"]["answers"][record["id"]] = distribution("contradicted", ce.STATUSES, .7492505619293989)
        report = pipeline.analyze(plan, records)
        self.assertEqual(report["provisional_candidate"], "battery")
        self.assertIn("Напряжение аккумулятора", report["clarifying_question"])
        alternative = next(c for c in report["candidates"] if c["code"] == "mechanical")
        self.assertEqual(alternative["assessment"], "uncertain")
        self.assertTrue(alternative["compatible"])

    def test_complete_compatible_candidate_moves_to_review(self):
        plan = pipeline.prepare(self.catalog, "Аккумуляторная дрель 18 В")
        report = pipeline.analyze(plan, answer_jobs(plan))
        self.assertEqual(report["status"], "ready_for_review")
        self.assertIsNone(report["clarifying_question"])
        self.assertIsNone(report["final_code"])

    def test_clarification_uses_short_catalog_unit(self):
        plan = pipeline.prepare(self.catalog, "Аккумуляторная дрель")
        report = pipeline.analyze(plan, answer_jobs(plan))
        self.assertEqual(report["clarifying_question"], "Укажите «Напряжение аккумулятора» (В).")

    def test_unsupported_numeric_rule_cannot_produce_a_provisional_candidate(self):
        rule = self.catalog["positions"][0]["characteristics"][1]["values"][0]["ranges"][0]
        rule["maxMathNotation"] = "unrecognized"
        plan = pipeline.prepare(self.catalog, "Аккумуляторная дрель 18 В")
        report = pipeline.analyze(plan, answer_jobs(plan))
        battery = next(c for c in report["candidates"] if c["code"] == "battery")
        self.assertEqual(battery["assessment"], "uncertain")
        self.assertIsNone(report["provisional_candidate"])

    def test_distinct_names_are_not_crowded_out_by_duplicate_versions(self):
        catalog = catalog_fixture()
        catalog["positions"] = []
        for index in range(5):
            position = deepcopy(self.catalog["positions"][0])
            position.update(key=f"a{index}@1", code=f"a{index}", name="Стул ученический")
            catalog["positions"].append(position)
        alternative = deepcopy(position)
        alternative.update(key="b@1", code="b", name="Стул на деревянном каркасе")
        catalog["positions"].append(alternative)
        result = pipeline.retrieve(catalog, "Нужен стул.", top_k=2)
        self.assertEqual(len({p["name"] for p in result["positions"]}), 2)
        self.assertTrue(result["truncated"])

    def test_unsupported_object_and_budget_do_not_start_inference(self):
        plan = pipeline.prepare(self.catalog, "Нужен ноутбук.")
        self.assertFalse(plan["jobs"])
        self.assertEqual(pipeline.analyze(plan, [])["status"], "retrieval_miss")
        with self.assertRaisesRegex(ValueError, "above"):
            pipeline.prepare(self.catalog, "Дрель 18 В.", max_questions=1)


class FollowupTests(unittest.TestCase):
    def test_numeric_ab_keeps_input_instructions_and_labels_identical(self):
        jobs = ce.followup_jobs()
        self.assertEqual(len(jobs), 29)
        for raw, normalized in zip(jobs[:12:2], jobs[1:12:2]):
            body = deepcopy(normalized["body"])
            body["questions"]["voltage"]["criteria"] = raw["body"]["questions"]["voltage"]["criteria"]
            self.assertEqual(body, raw["body"])
            self.assertEqual(raw["expected"], normalized["expected"])
        for job in jobs:
            for qid, expected in job["expected"].items():
                self.assertIn(expected, job["body"]["questions"][qid]["criteria"])

    def test_precision_recall_errors_and_empty_denominators(self):
        records = [{"experiment": "fact_followup", "expected": {"fact": expected},
                    "response": {"answers": {"fact": distribution(predicted, ce.STATUSES)}}}
                   for expected, predicted in (("supported", "supported"), ("unknown", "supported"), ("supported", "unknown"))]
        records.append({"experiment": "fact_followup", "expected": {"fact": "supported"}, "error": "timeout"})
        metrics = ce.supported_metrics(records)
        self.assertEqual(metrics["supported_precision"], .5)
        self.assertEqual(metrics["supported_recall"], .5)
        self.assertEqual(metrics["accepted_unsupported_additions"], 1)
        self.assertEqual(metrics["errors"], 1)
        self.assertIsNone(ce.supported_metrics([])["supported_precision"])
        report = ce.followup_report([], ce.followup_jobs())
        self.assertFalse(report["complete"])
        self.assertEqual(len(report["numeric_pairs"]), 6)
        self.assertEqual(report["numeric_pairs"][0]["raw"], {"error": "not executed"})

    def test_generic_numeric_binding_and_followup_report_are_saved(self):
        class FakeClient:
            base_url = "offline://fixture"
            timeout = 1
            def health(self):
                return {"model": ce.MODEL}
            def infer(self, body):
                return {"request": body, "response": {"model": ce.MODEL, "answers": {
                    qid: distribution("unknown", question["criteria"]) for qid, question in body["questions"].items()}}, "elapsed_seconds": .1}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "binding"
            plan = pipeline.prepare(catalog_fixture(), "Дрель 18 В.")
            records, _ = ce.run_jobs(FakeClient(), plan["jobs"], path)
            self.assertIn("bound_measurement", records[-1])
            followup = Path(tmp) / "followup"
            ce.run_jobs(FakeClient(), ce.followup_jobs(), followup)
            report = json.loads((followup / "followup_report.json").read_text())
            self.assertTrue(report["complete"])
            self.assertEqual(report["supported_facts"]["evaluated"], 17)


class BatchingTests(unittest.TestCase):
    @staticmethod
    def wire_records(plan, logical_records):
        by_id = {record["id"]: record for record in logical_records}
        records = []
        for request in plan["requests"]:
            answers = {}
            for part in request["parts"]:
                logical = by_id[part["job"]["id"]]
                answers.update({wire_id: logical["response"]["answers"][qid]
                                for qid, wire_id in part["question_ids"].items()})
            records.append(dict({k: v for k, v in request.items() if k != "body"},
                                request=request["body"], response={"model": ce.MODEL, "answers": answers}))
        return records

    def test_numeric_ids_do_not_collide_and_batched_analysis_matches_original(self):
        catalog = catalog_fixture()
        catalog["positions"][0]["characteristics"].append(dict(
            code="motor", name="Напряжение двигателя", type="2", kind="2", required=True,
            values=[dict(text="", unit_code="222", exact=["12"], ranges=[])]))
        text = "Аккумуляторная дрель 18 В. Напряжение двигателя 12 В."
        baseline = pipeline.prepare(catalog, text)
        plan = pipeline.prepare(catalog, text, batch_size=8)
        logical = answer_jobs(plan)
        for record in logical:
            if record.get("numeric_property", {}).get("name") == "Напряжение двигателя":
                record["response"]["answers"]["measurement"] = distribution(
                    "span_1", record["request"]["questions"]["measurement"]["criteria"])
        records = self.wire_records(plan, logical)
        self.assertEqual(len(plan["requests"]), 1)
        self.assertEqual(len(records[0]["request"]["questions"]), 5)
        self.assertEqual(pipeline.analyze(plan, records), pipeline.analyze(baseline, logical))
        self.assertEqual(len(pipeline.analyze(plan, records)["numeric_bindings"]), 2)
        restored = pipeline.unpack_records(records)
        self.assertEqual([r["request"] for r in restored], [j["body"] for j in plan["jobs"]])

    def test_limits_small_batches_and_distinct_inputs(self):
        for size in (1, 2, 3, 4, 64):
            with self.subTest(size=size):
                plan = pipeline.prepare(catalog_fixture(), "Дрель 18 В", batch_size=size)
                self.assertTrue(all(len(request["body"]["questions"]) <= size for request in plan["requests"]))
                self.assertEqual(sum(len(request["body"]["questions"]) for request in plan["requests"]), plan["question_count"])
        jobs = pipeline.prepare(catalog_fixture(), "Дрель 18 В")["jobs"]
        self.assertIs(pipeline.batch_jobs(jobs, 0), jobs)
        other = deepcopy(jobs[0])
        other["body"]["state"] = "Другой товар"
        self.assertEqual(len(pipeline.batch_jobs([jobs[0], other], 64)), 2)
        other["body"]["state"] = jobs[0]["body"]["state"]
        other["body"]["model"] = "another-model"
        self.assertEqual(len(pipeline.batch_jobs([jobs[0], other], 64)), 2)
        with self.assertRaises(ValueError):
            pipeline.batch_jobs(jobs, 65)

    def test_partial_or_failed_batch_never_claims_complete_inference(self):
        plan = pipeline.prepare(catalog_fixture(), "Дрель 18 В", batch_size=8)
        records = self.wire_records(plan, answer_jobs(plan))
        categorical = next(part for part in records[0]["parts"] if part["job"]["experiment"] == "pipeline_facts")
        del records[0]["response"]["answers"][next(iter(categorical["question_ids"].values()))]
        self.assertFalse(pipeline.analyze(plan, records)["complete_inference"])
        del records[0]["response"]
        records[0]["error"] = "timeout"
        restored = pipeline.unpack_records(records)
        self.assertTrue(all(record["error"] == "timeout" and "response" not in record for record in restored))
        self.assertEqual(pipeline.analyze(plan, records)["status"], "incomplete_inference")

    def test_batch_evidence_replays_as_original_or_batched_plan(self):
        plan = pipeline.prepare(catalog_fixture(), "Дрель 18 В", batch_size=8)
        records = self.wire_records(plan, answer_jobs(plan))
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "requests.jsonl").write_text("\n".join(json.dumps(r) for r in records))
            original = pipeline.prepare(catalog_fixture(), "Дрель 18 В")
            for target in (plan, original):
                replayed = pipeline.replay(target, [directory])
                self.assertTrue(pipeline.analyze(target, replayed)["complete_inference"])
                self.assertEqual(pipeline.analyze(target, replayed), pipeline.analyze(plan, records))


class ReplayTests(unittest.TestCase):
    def test_replay_requires_exact_input_questions_and_catalog_snapshot(self):
        plan = pipeline.prepare(catalog_fixture(), "Дрель 18 В.")
        records = answer_jobs(plan)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            path = directory / "requests.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in records))
            self.assertTrue(pipeline.analyze(plan, pipeline.replay(plan, [directory]))["complete_inference"])
            records[-1]["request"]["state"] = "Другой товар"
            path.write_text("\n".join(json.dumps(r) for r in records))
            self.assertFalse(pipeline.analyze(plan, pipeline.replay(plan, [directory]))["complete_inference"])
            (directory / "manifest.json").write_text(json.dumps({"catalog_sha256": "different"}))
            with self.assertRaisesRegex(ValueError, "snapshot differs"):
                pipeline.replay(plan, [directory])


if __name__ == "__main__":
    unittest.main()
