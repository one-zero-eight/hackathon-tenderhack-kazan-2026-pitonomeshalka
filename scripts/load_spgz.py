"""Load the СПГЗ workbooks (data/xlsx/*.xlsx) into PostgreSQL.

Лист1 holds СТЕ items, Лист2 holds КПГЗ category characteristics with their
linked reference (эталонная) СПГЗ characteristics. A row that cannot be trusted
is skipped and listed in data/spgz_rejects.tsv.
"""

import re
from collections import Counter
from datetime import date, datetime, time
from pathlib import Path

import openpyxl

if __package__:
    from .dbutil import MAX_VALUE_LENGTH, copy
else:
    from dbutil import MAX_VALUE_LENGTH, copy

DATA = Path(__file__).resolve().parents[1] / "data"
STE_HEADER = ("ID СТЕ", "Наименование СТЕ", "Модель", "Производитель", "Страна происхождения", "Характеристики")
CHARACTERISTIC_HEADER = (
    "Конечная категория ПП", "Код КПГЗ", "Наименование кода КПГЗ", "Название характеристики",
    "Тип (базовая/эталонная/категореобразующая)", "Тип характеристики", "Значения характеристики",
    "Единица измерения", "ID связанной эталонной характеристики СПГЗ",
    "Наименование связанной эталонной характеристики СПГЗ", "Значения связанной эталонной характеристики СПГЗ",
)
ROLE = {"Базовая": "base", "Эталонная": "reference", "Категореобразующая": "category"}
VALUE_TYPE = {
    "Текст": "text", "Справочник": "dict", "Признак": "flag", "Целое числовое значение": "int",
    "Дробное числовое значение": "decimal", "Диапазон": "range",
}
KPGZ_CODE = re.compile(r"\d{2}(?:\.\d{2})+")
REF_BLOCK = re.compile(r"(?:\A| \| )(\d+): ?")  # "123: v1; v2 | 456: v3"
EXCEL_CELL_LIMIT = 32759  # longer text was cut off by Excel; the last item is incomplete


def cell(value):
    """Cell as stripped text. None if empty, or if Excel turned the text into a date."""
    if isinstance(value, (date, time)):  # datetime is a date
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip() or None if value is not None else None


def rows(workbook, sheet, header):
    """Yield (row number, cells) of the non-blank data rows, after checking the header."""
    sheet_rows = workbook[sheet].iter_rows(values_only=True)
    if tuple(next(sheet_rows)[:len(header)]) != header:
        raise ValueError(f"unexpected header in {sheet}")
    for number, row in enumerate(sheet_rows, 2):
        if any(value is not None for value in row):
            yield number, row


def defect(row, width):
    """Why the raw row is untrustworthy (shifted, pasted or evaluated by Excel), or None."""
    if any(value is not None for value in row[width:]):
        return "overflow_columns"
    for value in row[:width]:
        if isinstance(value, str) and (value.startswith("=") or "\t" in value):
            return "formula_or_tab"
        if value is not None and not isinstance(value, (str, int, float, date, time)):
            return "formula_or_tab"


def enum_items(value, truncated=False):
    """Distinct ';'-separated items; skips unresolved ids and prose that is not a value."""
    items = [item.strip() for item in value.split(";")]
    if truncated:
        items.pop()
    return [item for item in dict.fromkeys(items)
            if item and len(item) <= MAX_VALUE_LENGTH and not item.startswith("[не найдено значение ID")]


def ref_blocks(value):
    marks = list(REF_BLOCK.finditer(value))
    ends = [mark.start() for mark in marks[1:]] + [len(value)]
    return {mark.group(1): value[mark.end():end] for mark, end in zip(marks, ends)}


def ste_rows(workbook, workbook_id, name, rejects):
    for number, row in rows(workbook, "Лист1", STE_HEADER):
        ste_id, title, model, maker, country, attrs = (cell(value) for value in row[:6])
        reason = defect(row, 6) or (None if ste_id and ste_id.isdigit() and title else "bad_ste")
        if reason:
            rejects.append((name, "Лист1", number, reason))
            continue
        attributes = [a.strip() for a in (attrs or "").split(" | ") if a.strip()]
        yield int(ste_id), title, model, maker, country, attributes, workbook_id, number


def xlsx_paths(directory=DATA / "xlsx"):
    paths = sorted(path for path in directory.glob("*.xlsx") if path.is_file())
    if not paths:
        raise FileNotFoundError(f"no SPGZ workbooks in {directory}")
    return paths


def load(conn, import_sha256, source_file_ids, *, schema, paths=None):
    """Stage import-scoped rows; return rejects for publication after commit."""
    paths = xlsx_paths() if paths is None else paths
    rejects = []
    kpgz, refs = {}, {}
    characteristics, values, ref_values, links = [], [], set(), set()
    def scoped_copy(cur, table, columns, records):
        copy(cur, table, ("import_sha256",) + columns,
             ((import_sha256,) + tuple(row) for row in records), schema=schema)

    with conn.cursor() as cur:
        scoped_copy(cur, "workbook", ("id", "name", "source_file_id"),
                    ((i, path.stem, source_file_ids[f"xlsx/{path.name}"]) for i, path in enumerate(paths, 1)))
        for workbook_id, path in enumerate(paths, 1):
            workbook = openpyxl.load_workbook(path, read_only=True)
            scoped_copy(cur, "ste", ("id", "name", "model", "manufacturer", "country", "attrs", "src_workbook", "src_row"),
                 ste_rows(workbook, workbook_id, path.stem, rejects))
            for number, row in rows(workbook, "Лист2", CHARACTERISTIC_HEADER):
                category, code, kpgz_name, name, role, vtype, allowed, unit, ref_ids, ref_names, ref_text = (
                    cell(value) for value in row[:11])
                ids = re.split(r"\s*\|\s*", ref_ids) if ref_ids else []
                names = re.split(r"\s*\|\s*", ref_names) if ref_names else []
                reason = defect(row, 11)
                if reason is None and not (code and KPGZ_CODE.fullmatch(code)):
                    reason = "bad_kpgz_code"
                elif reason is None and not (category and kpgz_name and name and role in ROLE and vtype in VALUE_TYPE):
                    reason = "bad_characteristic"
                elif reason is None and not (all(i.isdigit() for i in ids) and len(ids) == len(names)):
                    reason = "bad_reference"
                if reason:
                    rejects.append((path.stem, "Лист2", number, reason))
                    continue

                characteristic_id = len(characteristics) + 1
                kpgz.setdefault(code, (kpgz_name, category))
                characteristics.append((characteristic_id, code, name, ROLE[role], VALUE_TYPE[vtype],
                                        unit, workbook_id, number))
                cut = allowed is not None and len(allowed) >= EXCEL_CELL_LIMIT
                values.extend((characteristic_id, item) for item in enum_items(allowed or "", cut))
                blocks = ref_blocks(ref_text or "")
                for ref_id, ref_name in zip(ids, names):
                    refs.setdefault(int(ref_id), ref_name)
                    links.add((characteristic_id, int(ref_id)))
                    ref_values.update((int(ref_id), item) for item in enum_items(blocks.get(ref_id, "")))
            workbook.close()

        scoped_copy(cur, "kpgz", ("code", "name", "category"), ((c, n, cat) for c, (n, cat) in kpgz.items()))
        scoped_copy(cur, "kpgz_characteristic", ("id", "kpgz_code", "name", "role", "value_type", "unit", "src_workbook", "src_row"), characteristics)
        scoped_copy(cur, "kpgz_value", ("characteristic_id", "text"), values)
        scoped_copy(cur, "spgz_ref", ("id", "name"), refs.items())
        scoped_copy(cur, "spgz_ref_value", ("ref_id", "text"), sorted(ref_values))
        scoped_copy(cur, "kpgz_characteristic_ref", ("characteristic_id", "ref_id"), sorted(links))

    print(f"spgz: {len(characteristics)} characteristics, {len(kpgz)} КПГЗ; rejected rows:",
          dict(Counter(f"{sheet}/{reason}" for _, sheet, _, reason in rejects)))
    return rejects


def write_rejects(rejects, path=DATA / "spgz_rejects.tsv"):
    path.write_text("workbook\tsheet\trow\treason\n" +
                    "".join("\t".join(map(str, row)) + "\n" for row in rejects), encoding="utf-8")
