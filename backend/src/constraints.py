"""Explicit catalogue constraints, independent of classifier and retrieval scores."""

from decimal import Decimal, InvalidOperation

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import Range

from backend.src.models import Okei, OkeiAlias
from experiments.classifier_experiments import normalize


def decimal(value):
    if isinstance(value, bool):
        raise ValueError("booleans are not numbers")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValueError("invalid numeric constraint") from error
    if not result.is_finite():
        raise ValueError("numeric constraints must be finite")
    return result


def numeric_range(value):
    if not isinstance(value, dict):
        point = decimal(value)
        return Range(point, point, bounds="[]")
    if set(value) - {"min", "max", "min_inclusive", "max_inclusive"}:
        raise ValueError("unknown interval fields")
    low, high = value.get("min"), value.get("max")
    low, high = decimal(low) if low is not None else None, decimal(high) if high is not None else None
    left, right = value.get("min_inclusive", True), value.get("max_inclusive", True)
    if not isinstance(left, bool) or not isinstance(right, bool):
        raise ValueError("inclusivity flags must be booleans")
    if low is None and high is None or (low is not None and high is not None and
                                      (low > high or (low == high and not (left and right)))):
        raise ValueError("requested interval is empty, reversed, or has no bounds")
    return Range(low, high, bounds=("[" if left else "(") + ("]" if right else ")"))


def validate(constraints):
    if not isinstance(constraints, list):
        raise ValueError("constraints must be a JSON array")
    for constraint in constraints:
        if not isinstance(constraint, dict) or set(constraint) - {"name", "code", "values", "value_ids", "unit", "extra"}:
            raise ValueError("unknown constraint fields")
        if not any(isinstance(constraint.get(key), str) and constraint[key].strip() for key in ("name", "code")):
            raise ValueError("constraint needs a name or scoped code")
        values, ids = constraint.get("values"), constraint.get("value_ids")
        if (values is None) == (ids is None):
            raise ValueError("provide exactly one of values or value_ids")
        selection = ids if ids is not None else values
        if not isinstance(selection, list) or not selection:
            raise ValueError("selection must be a nonempty array")
        if ids is not None and any(type(id) is not int or id < 1 for id in ids):
            raise ValueError("value_ids must be positive integers")
        for value in values or []:
            if not isinstance(value, str):
                numeric_range(value)
        if "unit" in constraint and not isinstance(constraint["unit"], str):
            raise ValueError("unit must be an OKEI code or alias")
        if "extra" in constraint and type(constraint["extra"]) is not bool:
            raise ValueError("extra must be a boolean")


def check(store, position, constraint, *, procurement=False):
    chars = [char for char in position.characteristics if char.actual and
             (char.code == constraint["code"] if constraint.get("code") else normalize(char.name) == normalize(constraint["name"]))]
    result = {"name": constraint.get("name"), "code": constraint.get("code")}

    def verdict(status, reason):
        return result | {"status": status, "reason": reason}

    if constraint.get("extra"):
        return verdict("contradiction" if procurement and position.no_new_features is True else "unknown",
                       "supplementary requirement; catalogue policy applies only to procurement")
    if len(chars) != 1:
        return verdict("unknown", "absent or ambiguous characteristic binding")
    char = chars[0]
    values = char.values
    result.update(name=char.name, code=char.code, choice=char.choice, required=char.required,
                  allowed=[{"id": value.id, "code": value.code, "text": value.text,
                            "spans": [str(span) for span in value.spans or []], "okei": value.okei} for value in values])
    if not values or any(value.issue for value in values):
        return verdict("unknown", "missing or malformed source values")
    if "value_ids" in constraint:
        selected = set(constraint["value_ids"])
        allowed = {value.id for value in values}
        if not selected <= allowed:
            return verdict("contradiction", "option ID does not belong to this characteristic/import")
        if "unit" in constraint:
            with store.session() as session:
                codes = set(session.scalars(select(Okei.code).where(Okei.code == constraint["unit"])))
                codes.update(session.scalars(select(OkeiAlias.okei).where(OkeiAlias.alias == normalize(constraint["unit"]))))
            if len(codes) != 1 or any(value.okei is None for value in values if value.id in selected):
                return verdict("unknown", "selected option units absent or unresolved")
            if any(value.okei not in codes for value in values if value.id in selected):
                return verdict("unknown", "different selected option units; no implicit conversion")
    elif not char.is_numeric:
        if any(not isinstance(value, str) for value in constraint["values"]):
            return verdict("unknown", "qualitative options need text or resolved IDs")
        selected_text = {normalize(value) for value in constraint["values"]}
        allowed_text = {normalize(value.text) for value in values if value.text}
        if not selected_text <= allowed_text:
            return verdict("unknown", "unlisted wording; resolve synonyms to an exact allowed option")
        selected = {value.id for value in values if normalize(value.text or "") in selected_text}
    else:
        unit = constraint.get("unit")
        with store.session() as session:
            codes = set(session.scalars(select(Okei.code).where(Okei.code == unit)))
            codes.update(session.scalars(select(OkeiAlias.okei).where(OkeiAlias.alias == normalize(unit or ""))))
            if len(codes) != 1 or any(value.okei is None for value in values):
                return verdict("unknown", "numeric units absent or unresolved")
            unit = codes.pop()
            # Aggregate the allowed union before testing full interval coverage, not overlap.
            schema = session.bind.dialect.identifier_preparer.quote_schema(store.catalogue_schema)
            ranges = [str(numeric_range(value)) for value in constraint["values"]]
            coverage = session.execute(text(f"""WITH allowed AS (
                SELECT range_agg(atom) AS spans FROM {schema}.ktru_value v, unnest(v.spans) atom
                WHERE v.import_sha256=:import_id AND v.position_code=:code
                  AND v.characteristic_code=:char AND v.okei=:unit
            ), wanted AS (SELECT range_agg(atom) AS spans FROM unnest(CAST(:ranges AS numrange[])) atom)
            SELECT allowed.spans @> wanted.spans FROM allowed,wanted"""),
                {"import_id": position.import_sha256, "code": position.code, "char": char.code,
                 "unit": unit, "ranges": ranges}).scalar_one()
        if coverage is None:
            return verdict("unknown", "different units; no implicit conversion")
        if not coverage:
            return verdict("contradiction", "requested numeric set is outside allowed values")
        return verdict("unknown" if procurement else "match",
                       "use source group IDs for procurement selection" if procurement else "entire numeric set is covered")
    if procurement:
        if char.choice == "one_of" and len(selected) != 1:
            return verdict("contradiction", "kind=2 permits one XML option group")
        if char.choice == "fixed" and selected != {value.id for value in values}:
            return verdict("contradiction", "kind=1 catalogue description cannot be narrowed")
    return verdict("match", "selected catalogue options are supported")
