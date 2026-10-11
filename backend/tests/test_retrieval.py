"""Family coverage must survive a full, diversified retrieval shortlist."""

import unittest
from unittest.mock import Mock

from backend.src import pipeline
from backend.src.models import KtruCharacteristic, KtruPosition, KtruValue
from backend.src.presentation import analysis_response
from backend.src.retrieval import EmbeddingRetriever
from backend.src.settings import Settings


TYPE_B = "25.73.30.171-00000001"
TYPE_A = "25.73.30.171-00000002"
PARENT = "25.73.30.171-00000003"
NAME = "Ключ гаечный разводной"


def wrench(code, value):
    return KtruPosition(
        import_sha256="fixture", code=code, version=2, name=NAME,
        parent_code=PARENT, parent_version=2,
        characteristics=[KtruCharacteristic(
            code="execution", name="Тип исполнения", actual=True, is_numeric=False,
            choice="fixed", required=True,
            values=[KtruValue(id=1 if value == "B" else 2, ordinal=0, text=value, spans=[])],
        )],
    )


def family():
    return {
        "code": PARENT, "version": 2, "name": NAME,
        "children": [{"code": code, "version": 2, "name": NAME} for code in (TYPE_B, TYPE_A)],
        "splitting_characteristics": [{
            "code": "execution", "name": "Тип исполнения", "name_key": "тип исполнения",
            "required": True, "is_numeric": False,
            "variants": [{
                "choice": "fixed", "required": True, "is_numeric": False, "domain": value,
                "children": [code],
                "values": [{"text": value, "okei": None, "issue": None, "spans": []}],
            } for code, value in ((TYPE_B, "B"), (TYPE_A, "A"))],
        }],
    }


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = wrench(TYPE_A, "A"), wrench(TYPE_B, "B")
        self.others = [KtruPosition(import_sha256="fixture", code=f"other_{i}", version=1,
                                    name=f"Другой товар {i}", characteristics=[]) for i in range(7)]
        self.store, self.client = Mock(), Mock()
        self.store.get_active_import.return_value = "fixture"
        self.store.has_embeddings.return_value = False
        self.store.get_family_splits.return_value = [family()]
        self.store.get_positions.return_value = [self.b]
        self.retriever = EmbeddingRetriever(self.store, Settings(), self.client)

    def retrieve(self, positions, top_k=8):
        self.store.search_catalogue.return_value = (
            positions, [{"code": p.code, "name": p.name, "score": 1 - i * .01}
                        for i, p in enumerate(positions)], 100,
        )
        return self.retriever.retrieve(NAME, top_k=top_k)

    def test_full_shortlist_reserves_sibling_before_lower_ranked_hits(self):
        found = self.retrieve([self.a, *self.others])
        self.assertEqual([p.code for p in found.positions],
                         [TYPE_A, TYPE_B, *(p.code for p in self.others[:6])])
        self.assertEqual(len(found.positions), 8)
        self.assertEqual([h["code"] for h in found.evidence], [p.code for p in found.positions])
        self.assertEqual(found.evidence[1]["method"], "family_sibling")
        self.store.get_positions.assert_called_once_with("fixture", [TYPE_B])
        self.client.embed.assert_not_called()

    def test_retrieved_sibling_is_reused_without_duplicate_or_reload(self):
        found = self.retrieve([self.a, *self.others[:6], self.b])
        self.assertEqual([p.code for p in found.positions[:2]], [TYPE_A, TYPE_B])
        self.assertEqual(len({p.code for p in found.positions}), 8)
        self.assertNotIn("method", found.evidence[1])
        self.store.get_positions.assert_not_called()

    def test_small_limit_keeps_complete_family_domains_without_exceeding_limit(self):
        found = self.retrieve([self.a], top_k=1)
        self.assertEqual([p.code for p in found.positions], [TYPE_A])
        self.assertEqual(found.families, [family()])
        self.store.get_positions.assert_not_called()
        plan = pipeline.prepare(found, NAME + ", тип исполнения B")
        self.assertEqual({h.value for h in plan.hypotheses}, {"A", "B"})

    def test_both_descriptions_keep_the_type_b_candidate_compatible(self):
        for suffix in ("", ", ручка противоскользящая"):
            with self.subTest(suffix=suffix):
                found = self.retrieve([self.a, *self.others])
                plan = pipeline.prepare(found, NAME + ", тип исполнения B" + suffix)
                records = []
                for job in plan.jobs:
                    values = {h.id: h.value for h in job.hypotheses}
                    answers = {}
                    for qid in job.body["questions"]:
                        choice = ("supported" if values[qid] == "B" else "contradicted") if qid in values else (
                            "supported" if any(p.name == NAME for p in job.positions) else "contradicted")
                        answers[qid] = {"choice": choice, "probabilities": {
                            key: .95 if key == choice else .05 / 3
                            for key in ("supported", "contradicted", "unknown", "conflicting")}}
                    records.append({"id": job.id, "response": {"answers": answers}})
                result = analysis_response(pipeline.analyze(plan, records), "fixture")
                candidates = {c.code: c for c in result.candidates}
                self.assertEqual(candidates[TYPE_B].status, "compatible")
                self.assertEqual(candidates[TYPE_A].status, "rejected")
                self.assertEqual(result.recommended_candidate, TYPE_B + "@2")
                self.assertTrue(result.complete_inference)


if __name__ == "__main__":
    unittest.main()
