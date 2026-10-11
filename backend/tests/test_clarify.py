import pytest

from backend.src.clarify import apply_option, build_clarification
from experiments.classifier_experiments import identity


CANDIDATES = [
    {"code": "10", "version": "1", "name": "Аккумуляторная дрель"},
    {"code": "20", "version": "1", "name": "Сетевая дрель"},
    {"code": "30", "version": "1", "name": "Ручная дрель"},
]


def result_with_splits(*splits):
    return {
        "candidates": CANDIDATES,
        "detected_families": [
            {
                "code": "family",
                "version": "1",
                "name": "Дрели",
                "resolved": False,
                "candidate_codes": ["10", "20", "30"],
                "splitting_characteristics": list(splits),
            }
        ],
    }


def split(name, resolved, options):
    return {
        "code": identity(name),
        "name": name,
        "required": True,
        "is_numeric": False,
        "resolved": resolved,
        "observed": False,
        "options": options,
    }


def option(text, children):
    return {"text": text, "spans": None, "okei": None, "issue": None, "children": children}


def test_unresolved_splitting_family_characteristic_precedes_product_fallback():
    result = result_with_splits(
        split("Тип питания", False, [
            option("От аккумулятора", ["10", "outside"]),
            option("От сети", ["20"]),
            option("Механический", ["30"]),
        ])
    )

    clarification = build_clarification(result, ["10", "20"], round_number=1)

    assert clarification["kind"] == "characteristic"
    assert clarification["question"] == "Укажите «Тип питания»."
    assert clarification["question_id"] == "clarification_" + identity(
        "1", "characteristic", "family", identity("Тип питания"), "10", "20"
    )
    assert clarification["manual_choice"] is False
    assert [item["text"] for item in clarification["options"]] == [
        "От аккумулятора", "От сети", "Ничего из перечисленного",
    ]
    assert [item["candidate_codes"] for item in clarification["options"]] == [
        ["10"], ["20"], [],
    ]
    assert clarification["options"][-1]["suggest_expand"] is True


def test_non_splitting_characteristic_is_skipped_for_product_fallback():
    result = result_with_splits(
        split("Цвет", False, [option("Любой", ["10", "20", "30"])]),
        split("Уже определено", True, [option("Да", ["10"]), option("Нет", ["20"])])
    )

    clarification = build_clarification(result, ["10", "20"], round_number=1)

    assert clarification["kind"] == "product"
    assert clarification["question"] == "Выберите вид товара."
    assert [item["text"] for item in clarification["options"]] == [
        "Аккумуляторная дрель", "Сетевая дрель", "Ничего из перечисленного",
    ]
    assert [item["candidate_codes"] for item in clarification["options"]] == [
        ["10"], ["20"], [],
    ]


def test_third_round_forces_manual_product_choice():
    result = result_with_splits(
        split("Тип питания", False, [option("От аккумулятора", ["10"]), option("От сети", ["20"])])
    )

    clarification = build_clarification(result, ["10", "20"], round_number=3)

    assert clarification["kind"] == "product"
    assert clarification["manual_choice"] is True
    assert len(clarification["options"]) == 3


def test_ids_are_stable_and_apply_option_intersects_current_candidates():
    clarification = build_clarification({"candidates": CANDIDATES, "detected_families": []}, ["20", "10"], 2)
    same = build_clarification({"candidates": CANDIDATES, "detected_families": []}, ["20", "10"], 2)

    assert clarification == same
    selected = next(item for item in clarification["options"] if item["candidate_codes"] == ["20"])
    assert selected["id"] == "option_" + identity(clarification["question_id"], "20")
    assert apply_option(clarification, selected["id"], ["10", "20", "30"]) == ["20"]


def test_apply_option_allows_none_but_rejects_a_stale_empty_intersection():
    clarification = build_clarification({"candidates": CANDIDATES, "detected_families": []}, ["10", "20"], 1)
    none = next(item for item in clarification["options"] if item["suggest_expand"])
    stale = next(item for item in clarification["options"] if item["candidate_codes"] == ["10"])

    assert apply_option(clarification, none["id"], ["10", "20"]) == []
    with pytest.raises(ValueError, match="clarification option does not match current candidates"):
        apply_option(clarification, stale["id"], ["20"])


@pytest.mark.parametrize("option_id", ["", "missing-option"])
def test_apply_option_rejects_empty_or_unknown_option(option_id):
    clarification = build_clarification({"candidates": CANDIDATES, "detected_families": []}, ["10", "20"], 1)

    with pytest.raises(ValueError, match="unknown or empty clarification option"):
        apply_option(clarification, option_id, ["10", "20"])
