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
