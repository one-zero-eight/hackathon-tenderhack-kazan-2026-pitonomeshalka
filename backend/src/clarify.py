"""Pure, deterministic clarification helpers for saved analysis results."""

from experiments.classifier_experiments import identity

CLARIFICATION_STATE = "clarification_state.json"


def initial_candidate_codes(result: dict) -> list[str]:
    """Live candidate codes from the saved result, in result order; rejected ones never ask questions."""
    return [candidate["code"] for candidate in result.get("candidates", [])
            if candidate.get("status") != "rejected"]


def _question_id(round_number, kind, source, candidate_codes):
    return "clarification_" + identity(
        str(round_number), kind, *source, *candidate_codes
    )


def _option(question_id, text, candidate_codes, *, suggest_expand=False):
    key = ("none",) if suggest_expand else tuple(candidate_codes)
    return {
        "id": "option_" + identity(question_id, *key),
        "text": text,
        "candidate_codes": candidate_codes,
        "suggest_expand": suggest_expand,
    }


def _none_option(question_id):
    return _option(
        question_id,
        "Ничего из перечисленного",
        [],
        suggest_expand=True,
    )


def _characteristic_question(result, candidate_codes, round_number):
    for family in result.get("detected_families", []):
        if family.get("resolved"):
            continue
        for characteristic in family.get("splitting_characteristics", []):
            if characteristic.get("resolved"):
                continue
            choices = []
            seen_groups = set()
            for value in characteristic.get("options", []):
                children = [code for code in candidate_codes if code in set(value.get("children", []))]
                group = tuple(children)
                if not value.get("text") or not group or group in seen_groups:
                    continue
                seen_groups.add(group)
                choices.append((value["text"], children))
            if len(seen_groups) < 2:
                continue
            question_id = _question_id(
                round_number,
                "characteristic",
                (family["code"], characteristic["code"]),
                candidate_codes,
            )
            return {
                "question_id": question_id,
                "kind": "characteristic",
                "question": f"Укажите «{characteristic['name']}».",
                "manual_choice": False,
                "allow_text": True,
                "options": [
                    _option(question_id, text, children)
                    for text, children in choices
                ] + [_none_option(question_id)],
            }
    return None


def _product_question(result, candidate_codes, round_number):
    candidates = {
        candidate["code"]: candidate
        for candidate in result.get("candidates", [])
        if candidate.get("code") in candidate_codes
    }
    question_id = _question_id(round_number, "product", (), candidate_codes)
    options = [
        _option(question_id, candidates[code]["name"], [code])
        for code in candidate_codes
        if code in candidates
    ]
    return {
        "question_id": question_id,
        "kind": "product",
        "question": "Выберите вид товара.",
        "manual_choice": round_number >= 3,
        "allow_text": True,
        "options": options + [_none_option(question_id)],
    }


def build_clarification(result: dict, candidate_codes: list[str], round_number: int) -> dict:
    """Build the next deterministic question from the saved result and current codes."""
    if round_number < 3:
        characteristic = _characteristic_question(result, candidate_codes, round_number)
        if characteristic is not None:
            return characteristic
    return _product_question(result, candidate_codes, round_number)


SKIP_OPTION_TEXT = "Оставить незаполненным"


def askable_values(characteristic) -> list:
    """Clean text values of a characteristic; span-only (numeric) and issued values never ask."""
    if characteristic.choice == "fixed" and len(characteristic.values) == 1:
        return []  # A fixed characteristic with one value is confirmed by the catalog itself.
    return [value for value in characteristic.values if value.text and not value.issue]


def required_characteristics(position) -> list:
    """Required and actual characteristics that need an answer, in stable characteristic-code order."""
    return sorted(
        (characteristic for characteristic in position.characteristics
         if characteristic.required and characteristic.actual and askable_values(characteristic)),
        key=lambda characteristic: characteristic.code,
    )


def build_required_question(position_code: str, characteristic) -> dict:
    """One required-characteristic question; options are the catalog text values plus a skip marker."""
    question_id = "clarification_req_" + identity(position_code, characteristic.code)
    return {
        "question_id": question_id,
        "kind": "required",
        # Not part of the public schema; the service records it in the confirmed list.
        "characteristic_code": characteristic.code,
        "question": f"Укажите «{characteristic.name}» позиции.",
        "manual_choice": False,
        "allow_text": True,
        "options": [
            {
                "id": "option_" + identity(question_id, value.id),
                "text": value.text,
                "candidate_codes": [position_code],
                "suggest_expand": False,
            }
            for value in askable_values(characteristic)
        ] + [_option(question_id, SKIP_OPTION_TEXT, [])],
    }


def next_required_question(position_code: str, position, answered_codes) -> dict | None:
    """The first unanswered required-characteristic question, or None when the final card is due.

    ``answered_codes`` covers both confirmed answers and explicit skips; skipped
    characteristics are left unfilled and never asked again.
    """
    answered = set(answered_codes or [])
    pending = [characteristic for characteristic in required_characteristics(position)
               if characteristic.code not in answered]
    if not pending:
        return None
    return build_required_question(position_code, pending[0])


def apply_option(clarification: dict, option_id: str, candidate_codes: list[str]) -> list[str]:
    """Apply a known option by intersecting it with the current candidate codes."""
    selected = next(
        (option for option in clarification.get("options", []) if option.get("id") == option_id),
        None,
    )
    if not option_id or selected is None:
        raise ValueError("unknown or empty clarification option")
    allowed = set(selected.get("candidate_codes", []))
    narrowed = [code for code in candidate_codes if code in allowed]
    if allowed and not narrowed:
        raise ValueError("clarification option does not match current candidates")
    return narrowed
