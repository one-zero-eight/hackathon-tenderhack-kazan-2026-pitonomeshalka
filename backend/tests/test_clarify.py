import pytest

from backend.src.clarify import (apply_option, build_clarification, build_required_question,
                                 next_required_question, required_characteristics)
from backend.src.models import KtruCharacteristic, KtruPosition, KtruValue
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


def required_position():
    """One askable required characteristic plus every shape that must not ask a question."""
    position = KtruPosition(import_sha256="import", code="30", version=1, name="Дрель ручная",
                            status="ACTIVE", units=["шт"], rubrics=[], rubric_codes=[])

    def characteristic(code, name, *, required=True, actual=True, choice="one_of"):
        return KtruCharacteristic(import_sha256="import", position_code="30", code=code, name=name,
                                  is_numeric=False, choice=choice, required=required, actual=actual)

    askable = characteristic("080", "Питание")
    askable.values.append(KtruValue(id=11, ordinal=0, text="От сети", okei=None))
    span_only = characteristic("090", "Мощность")  # numeric: no text values at all
    span_only.values.append(KtruValue(id=12, ordinal=0, text=None, okei="112", issue="диапазон"))
    fixed = characteristic("100", "Серия", choice="fixed")
    fixed.values.append(KtruValue(id=13, ordinal=0, text="Единая", okei=None))
    optional = characteristic("110", "Цвет", required=False)
    optional.values.append(KtruValue(id=14, ordinal=0, text="Красный", okei=None))
    historical = characteristic("120", "Старое", actual=False)
    historical.values.append(KtruValue(id=15, ordinal=0, text="Любой", okei=None))
    issued = characteristic("130", "Брак")
    issued.values.append(KtruValue(id=16, ordinal=0, text="От сети", okei=None, issue="игнорируется"))
    later = characteristic("140", "Патрон")
    later.values.append(KtruValue(id=17, ordinal=0, text="Под ключ", okei=None))
    position.characteristics.extend([askable, span_only, fixed, optional, historical, issued, later])
    return position


def test_required_question_is_built_from_text_values_with_a_skip_marker():
    characteristic = next(item for item in required_position().characteristics if item.code == "080")

    question = build_required_question("30", characteristic)

    assert question["kind"] == "required"
    assert question["question_id"] == "clarification_req_" + identity("30", "080")
    assert question["question"] == "Укажите «Питание» позиции."
    assert question["allow_text"] is True
    assert question["manual_choice"] is False
    assert [(option["id"], option["text"], option["candidate_codes"], option["suggest_expand"])
            for option in question["options"]] == [
        ("option_" + identity(question["question_id"], 11), "От сети", ["30"], False),
        ("option_" + identity(question["question_id"]), "Оставить незаполненным", [], False),
    ]


def test_only_askable_required_actual_characteristics_ask_questions_in_code_order():
    assert [characteristic.code for characteristic in required_characteristics(required_position())] \
        == ["080", "140"]


def test_next_required_question_skips_answered_codes_and_stops():
    position = required_position()

    first = next_required_question("30", position, [])
    second = next_required_question("30", position, ["080"])

    assert first["characteristic_code"] == "080"
    assert second["characteristic_code"] == "140"
    assert next_required_question("30", position, ["080", "140"]) is None
