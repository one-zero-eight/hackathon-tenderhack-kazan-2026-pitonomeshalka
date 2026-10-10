"""Offline checks for the team API contract and experiment interpretation."""
import io
import json
import unittest
from unittest.mock import patch

import nimble_experiments as experiment


class ProtocolTests(unittest.TestCase):
    def test_request_matches_team_handler_and_preserves_russian(self):
        job = experiment.smoke_jobs()[0]
        answer = {"type": "choice", "choice": "supported", "confidence": .9,
                  "probabilities": {"supported": .9, "contradicted": .02, "unknown": .06, "conflicting": .02}}
        response = {"model": experiment.MODEL, "answers": {"fact": answer}, "usage": {"input_tokens": 10, "output_tokens": 0}}
        def fake_urlopen(request, timeout):
            self.assertEqual(request.full_url, "http://127.0.0.1:8769/v1/systemone")
            body = json.loads(request.data)
            self.assertEqual(body["state"], "Нужна аккумуляторная дрель.")
            question = body["questions"]["fact"]
            self.assertEqual(question["type"], "choice")
            self.assertIn("instructions", question)
            self.assertEqual(set(question["criteria"]), set(experiment.STATUSES))
            return io.BytesIO(json.dumps(response).encode())
        with patch.object(experiment, "urlopen", fake_urlopen):
            result = experiment.SystemOneClient().infer(job["body"])
        self.assertEqual(result["response"], response)

    def test_invalid_distribution_is_rejected(self):
        job = experiment.smoke_jobs()[0]
        response = {"model": experiment.MODEL, "answers": {"fact": {"choice": "supported", "probabilities": {k: .5 for k in experiment.STATUSES}}}}
        with patch.object(experiment, "urlopen", return_value=io.BytesIO(json.dumps(response).encode())):
            with self.assertRaisesRegex(ValueError, "sum to one"):
                experiment.SystemOneClient().infer(job["body"])

    def test_numeric_spans_and_unit_conversion(self):
        text = "Дрель 0,018 кВ; зарядник 220 В; ширина упаковки 12 см."
        spans = experiment.measurements(text)
        self.assertEqual([s["value"] for s in spans], ["18.000", "220", "120"])
        self.assertEqual([s["okei"] for s in spans], ["222", "222", "003"])
        for span in spans:
            self.assertEqual(text[span["start"]:span["end"]], span["raw"])
        for job in experiment.numeric_jobs():
            expected = job["expected"]["voltage"]
            self.assertIn(expected, job["body"]["questions"]["voltage"]["criteria"])


class NarrowingTests(unittest.TestCase):
    def setUp(self):
        self.facts = [
            {"id": "battery", "name": "Тип питания", "value": "От аккумулятора", "unit_code": ""},
            {"id": "mains", "name": "Тип питания", "value": "От сети", "unit_code": ""},
        ]
        def position(code, value):
            return {"code": code, "version": "1", "name": "Дрель", "characteristics": [{"name": "Тип питания", "kind": "1", "values": [{"text": value, "unit_code": ""}]}]}
        self.positions = [position("battery_code", "От аккумулятора"), position("mains_code", "От сети")]

    def records(self, **statuses):
        return [{"response": {"answers": {fid: {"choice": status, "probabilities": {status: .95}} for fid, status in statuses.items()}}}]

    def test_missing_information_keeps_both_candidates(self):
        candidates = experiment.narrow_candidates(self.positions, self.facts, self.records(battery="unknown", mains="unknown"))
        self.assertTrue(all(c["compatible"] for c in candidates))

    def test_confirmed_power_excludes_incompatible_position(self):
        candidates = experiment.narrow_candidates(self.positions, self.facts, self.records(battery="supported", mains="contradicted"))
        self.assertEqual([c["code"] for c in candidates if c["compatible"]], ["battery_code"])

    def test_conflicting_positive_values_do_not_eliminate_everything(self):
        candidates = experiment.narrow_candidates(self.positions, self.facts, self.records(battery="supported", mains="supported"))
        self.assertTrue(all(c["compatible"] for c in candidates))
        self.assertTrue(all(c["uncertain"] for c in candidates))

    def test_failed_requests_are_counted_in_diagnostic_denominator(self):
        record = {"experiment": "smoke", "expected": {"fact": "supported"}, "error": "timeout"}
        summary = experiment.summarize([record])["experiments"]["smoke"]
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["accuracy"], 0)


if __name__ == "__main__":
    unittest.main()
