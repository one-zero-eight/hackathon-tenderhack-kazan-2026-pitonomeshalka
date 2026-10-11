"""Load data/ktru/*.xml into PostgreSQL, one latest version per code.

Winners rank by version, then updateDate, without preferring an older active
version. parse(data) is pure and returns COPY-ready (position, characteristics,
values); each XML values/value produces one row, even when its payload is invalid.
"""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path

from lxml import etree

if __package__:
    from .dbutil import copy, insert_missing
else:
    from dbutil import copy, insert_missing

NS = "{http://zakupki.gov.ru/oos/types/1}"
XML_DIR = Path(__file__).resolve().parents[1] / "data" / "ktru"
CHOICE = {"1": "fixed", "2": "one_of", "3": "many_of"}
BOOLEAN = {"true": True, "false": False, "1": True, "0": False}
BATCH = 5000  # positions per COPY round

POSITION_COLUMNS = (
    "code", "version", "updated", "name", "okpd2", "status", "terminated_on", "is_template",
    "parent_code", "parent_version", "applies_from", "applies_to", "no_new_features",
    "no_new_features_reason", "units", "rubrics", "description",
    "xml_id", "version_code", "external_code", "rubric_codes",
)
CHARACTERISTIC_COLUMNS = (
    "position_code", "code", "name", "is_numeric", "choice", "required", "actual", "choice_type",
)
VALUE_COLUMNS = (
    "position_code", "characteristic_code", "code", "text", "spans", "okei", "issue", "value_format", "ordinal",
)


@cache
def _path(path):
    return "/".join(NS + part for part in path.split("/"))


def text(node, path) -> str | None:
    """Stripped text at a slash-separated path, or None if absent/empty."""
    value = node.findtext(_path(path)) if node is not None else None
    return value.strip() or None if value else None


def required_text(node, path) -> str:
    value = text(node, path)
    if value is None:
        raise ValueError(f"missing required XML field {path} at line {node.sourceline}")
    return value


def children(node, path):
    return node.findall(_path(path)) if node is not None else []


def xml_paths(directory=XML_DIR):
    paths = sorted(path for path in directory.glob("*.xml") if path.is_file())
    if not paths:
        raise FileNotFoundError(f"no KTRU XML files in {directory}; refusing an empty import")
    return paths


def positions(paths=None):
    """Yield (address, <data>); address is (file, line). Elements expire on advance."""
    for path in xml_paths() if paths is None else paths:
        with path.open("rb") as source:
            for _, position in etree.iterparse(source, tag=NS + "position", resolve_entities=False, no_network=True):
                data = position.find(NS + "data")
                if data is None:
                    raise ValueError(f"missing position data in {path.name}:{position.sourceline}")
                yield (path.name, data.sourceline), data
                position.clear()
                while position.getprevious() is not None:
                    del position.getparent()[0]


def updated(data):
    value = datetime.fromisoformat(required_text(data, "updateDate"))
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def pick_winners(records=None):
    """Return winning addresses; optional iterable of (address, data) enables pure tests."""
    best = {}
    for address, data in positions() if records is None else records:
        rank = (int(required_text(data, "version")), updated(data))
        code = required_text(data, "code")
        if code not in best or rank > best[code][0]:
            best[code] = (rank, address)
    return {address for _, address in best.values()}


def number(value):
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"invalid number {value!r}") from error
    if not result.is_finite():
        raise ValueError(f"non-finite number {value!r}")
    return result


def span(low, low_op, high, high_op):
    """numrange literal; invalid/reversed/empty intervals raise ValueError."""
    if low is None and high is None:
        raise ValueError("missing both interval bounds")
    if (low is None and low_op is not None) or (high is None and high_op is not None):
        raise ValueError("operator without a bound")
    if (low is not None and low_op not in {"greater", "greaterOrEqual"}) or (
            high is not None and high_op not in {"less", "lessOrEqual"}):
        raise ValueError("missing or unknown interval operator")
    low = number(low) if low is not None else None
    high = number(high) if high is not None else None
    low_closed, high_closed = low_op == "greaterOrEqual", high_op == "lessOrEqual"
    if low is not None and high is not None:
        if low > high:
            raise ValueError("reversed interval")
        if low == high and not (low_closed and high_closed):
            raise ValueError("empty interval")
    return f"{'[' if low_closed else '('}{low if low is not None else ''},{high if high is not None else ''}{']' if high_closed else ')'}"



def numeric_spans(value):
    """Collect a group's spans and issues without treating unknown XML as unbounded."""
    spans, issues = [], []
    for container in children(value, "valueSet") + children(value, "rangeSet"):
        point_set = container.tag == NS + "valueSet"
        expected = NS + ("concreteValue" if point_set else "valueRange")
        if len(container) == 0:
            issues.append("invalid span: empty numeric set")
        for node in container:
            try:
                if node.tag != expected:
                    raise ValueError("unknown numeric element")
                if point_set:
                    if len(node):
                        raise ValueError("nested concrete value")
                    point = number(node.text.strip() if node.text else None)
                    spans.append(f"[{point},{point}]")
                else:
                    tags = [n.tag for n in node]
                    allowed = {NS + tag for tag in ("min", "minMathNotation", "max", "maxMathNotation")}
                    if any(tag not in allowed for tag in tags) or len(tags) != len(set(tags)):
                        raise ValueError("unknown or repeated interval element")
                    if any(len(n) or not (n.text or "").strip() for n in node):
                        raise ValueError("empty or nested interval element")
                    spans.append(span(text(node, "min"), text(node, "minMathNotation"),
                                      text(node, "max"), text(node, "maxMathNotation")))
            except ValueError as error:
                issues.append(f"invalid span: {error}")
    return spans, issues


def parse(data):
    """Return three COPY-ready row collections, with no database or dictionary state.

    spans is a list of numrange literals, or None. Any malformed part invalidates
    the whole numeric group; issue retains the offending XML for review. Embedding
    and identity columns are omitted so PostgreSQL supplies NULLs and fresh ids.
    """
    code = required_text(data, "code")
    parent_version = text(data, "parentPositionInfo/version")
    cancelled, ends, flag = text(data, "cancelInfo/cancelDate"), text(data, "applicationDateEnd"), text(data, "noNewFeatures")
    position = (
        code, int(required_text(data, "version")), updated(data), required_text(data, "name"), required_text(data, "OKPD2/code"),
        required_text(data, "status"), cancelled and date.fromisoformat(cancelled[:10]), BOOLEAN[required_text(data, "isTemplate")],
        text(data, "parentPositionInfo/code"), int(parent_version) if parent_version is not None else None,
        date.fromisoformat(required_text(data, "applicationDateStart")[:10]), ends and date.fromisoformat(ends[:10]),
        BOOLEAN[flag] if flag is not None else None, text(data, "noNewFeaturesReason"),
        [unit for n in children(data, "OKEIs/OKEI") if (unit := text(n, "code")) is not None],
        [text(n, "name") for n in children(data, "rubricators/rubricatorInfo")], text(data, "nsiDescription"),
        text(data, "id"), text(data, "versionCode"), text(data, "externalCode"),
        [text(n, "code") for n in children(data, "rubricators/rubricatorInfo")],
    )
    characteristics, values = [], []
    for node in children(data, "characteristics/characteristic"):
        char_code, is_numeric = required_text(node, "code"), {"1": False, "2": True}[required_text(node, "type")]
        choice_type = text(node, "choiceType")
        characteristics.append((code, char_code, required_text(node, "name"), is_numeric, CHOICE[required_text(node, "kind")],
                                BOOLEAN[required_text(node, "isRequired")], BOOLEAN[required_text(node, "actual")],
                                int(choice_type) if choice_type is not None else None))
        for ordinal, value in enumerate(children(node, "values/value")):
            quality = text(value, "qualityDescription")
            spans, issues = numeric_spans(value)
            numeric_group = bool(children(value, "valueSet") or children(value, "rangeSet"))
            known = {NS + tag for tag in ("valueCode", "qualityDescription", "valueSet", "rangeSet", "OKEI", "valueFormat")}
            if any(n.tag not in known for n in value):
                issues.append("invalid payload: unknown value element")
            if (is_numeric and quality is not None) or (not is_numeric and numeric_group):
                issues.append("invalid payload: characteristic type disagrees with value")
            if quality is None and not spans and not issues:
                issues.append("invalid payload: missing qualitative text or numeric spans")
            issue = None
            if issues:
                source = etree.tostring(value, encoding="unicode", with_tail=False)
                issue = "\n".join(issues) + f"\nsource value: {source}"
            values.append((code, char_code, text(value, "valueCode"), quality,
                           spans if spans and issue is None else None, text(value, "OKEI/code"),
                           issue, text(value, "valueFormat"), ordinal))
    return position, characteristics, values


def load(conn, import_sha256, source_file_ids, *, schema, paths=None):
    """COPY into an existing transaction; the caller owns commit and activation.

    source_file_ids maps manifest names (xml/<filename>) to SourceFile ids.
    """
    paths = xml_paths() if paths is None else paths
    winners = pick_winners(positions(paths))
    okpd2, okei = {}, {}
    invalid_spans, issue_values = 0, 0

    def flush(cur, batch):
        copy(cur, "ktru_position", ("import_sha256",) + POSITION_COLUMNS + ("source_file_id", "source_line"),
             ((import_sha256,) + p for p, _, _ in batch), schema=schema)
        copy(cur, "ktru_characteristic", ("import_sha256",) + CHARACTERISTIC_COLUMNS,
             ((import_sha256,) + c for _, cs, _ in batch for c in cs), schema=schema)
        copy(cur, "ktru_value", ("import_sha256",) + VALUE_COLUMNS,
             ((import_sha256,) + v for _, _, vs in batch for v in vs), schema=schema)

    with conn.cursor() as cur:
        batch, count = [], 0
        for address, data in positions(paths):
            if address not in winners:
                continue
            position, characteristics, values = parse(data)
            position += (source_file_ids[f"xml/{address[0]}"], address[1])
            batch.append((position, characteristics, values))
            count += 1
            dictionary_code = text(data, "OKPD2/code")
            if dictionary_code:
                okpd2.setdefault(dictionary_code, text(data, "OKPD2/name") or dictionary_code)
            for unit in children(data, "OKEIs/OKEI") + children(data, "characteristics/characteristic/values/value/OKEI"):
                unit_code = text(unit, "code")
                if unit_code:
                    okei.setdefault(unit_code, text(unit, "name") or unit_code)
            for row in values:
                if (issue := row[VALUE_COLUMNS.index("issue")]) is not None:
                    issue_values += 1
                    invalid_spans += sum(line.startswith("invalid span:") for line in issue.splitlines())
            if len(batch) == BATCH:
                flush(cur, batch)
                batch = []
        if count == 0:
            raise ValueError("KTRU XML files contain no positions; refusing an empty import")
        flush(cur, batch)
        insert_missing(cur, "okpd2", ("code", "name"), sorted(okpd2.items()), schema=schema)
        insert_missing(cur, "okei", ("code", "name"), sorted(okei.items()), schema=schema)
    print(f"ktru: {count} positions loaded, {invalid_spans} invalid spans in {issue_values} issue values (retained)")
    return {"positions": count, "invalid_spans": invalid_spans, "issue_values": issue_values}
