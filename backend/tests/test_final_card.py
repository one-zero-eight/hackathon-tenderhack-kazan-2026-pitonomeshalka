"""Final KTRU card is rendered from ORM catalogue objects and the recorded answer trace."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.dialects.postgresql import Range

from backend.src.final_card import build_final_card
from backend.src.models import KtruCharacteristic, KtruPosition, KtruValue


def position():
    root = KtruPosition(
        import_sha256="import-sha", code="25.73.011.111", version=3,
        updated=datetime(2026, 1, 15, 10, 30), name="Отвёртка аккумуляторная",
        status="ACTIVE", applies_from=date(2025, 1, 1), units=["шт"],
        rubrics=["Инструмент"], rubric_codes=["116"], source_file_id=7, source_line=42,
    )
    actual = KtruCharacteristic(
        import_sha256="import-sha", position_code="25.73.011.111", code="080",
        name="Тип питания", is_numeric=False, choice="one_of", required=True, actual=True,
    )
    actual.values.extend([
        KtruValue(id=11, ordinal=0, text="От аккумулятора", okei="168"),
        KtruValue(id=12, ordinal=1, text=None, spans=[Range(Decimal("3"), Decimal("6"), bounds="[)")],
                  okei="112", value_format="N"),
    ])
    historical = KtruCharacteristic(
        import_sha256="import-sha", position_code="25.73.011.111", code="001",
        name="Устаревшая характеристика", is_numeric=False, choice="many_of",
        required=False, actual=False,
    )
    historical.values.append(KtruValue(id=13, ordinal=0, text="Любой", okei=None))
    root.characteristics.extend([historical, actual])
    return root


def test_card_keeps_position_identity_status_period_and_review_flag():
    card = build_final_card(position(), [{"question_id": "question-a", "option_id": "option-a"}])

    assert card["code"] == "25.73.011.111"
    assert card["version"] == "3"
    assert card["name"] == "Отвёртка аккумуляторная"
    assert card["status"] == "ACTIVE"
    assert card["applies_from"] == "2025-01-01"
    assert card["applies_to"] is None
    assert card["units"] == ["шт"]
    assert card["requires_review"] is True


def test_card_lists_each_actual_characteristic_with_all_values_and_spans():
    card = build_final_card(position(), [{"question_id": "question-a", "option_id": "option-a"}])

    assert [characteristic["code"] for characteristic in card["characteristics"]] == ["080"]
    characteristic = card["characteristics"][0]
    assert characteristic["name"] == "Тип питания"
    assert characteristic["required"] is True
    assert characteristic["choice"] == "one_of"
    assert characteristic["is_numeric"] is False
    assert characteristic["units"] == ["112", "168"]
    assert [(value["id"], value["text"], value["issue"]) for value in characteristic["values"]] == [
        (11, "От аккумулятора", None), (12, None, None),
    ]
    assert characteristic["values"][0]["spans"] == []
    assert characteristic["values"][1]["spans"] == [
        {"lower": "3", "upper": "6", "bounds": "[)", "empty": False},
    ]


def test_rationale_is_deterministic_and_derived_from_answers():
    answers = [{"question_id": "question-a", "option_id": "option-a"}]
    first = build_final_card(position(), answers)

    assert first == build_final_card(position(), [{"question_id": "question-a", "option_id": "option-a"}])
    assert first["rationale"] == build_final_card(position(), list(answers))["rationale"]
    assert "question-a" in first["rationale"]
    assert "option-a" in first["rationale"]
    assert "25.73.011.111" in first["rationale"]
    assert build_final_card(position(), [{"question_id": "question-b", "option_id": "option-b"}])["rationale"] \
        != first["rationale"]
