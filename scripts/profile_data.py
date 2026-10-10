"""Audit supplied Tender Hack data using only the Python standard library.

Reads all workbook rows and active KTRU positions. Inactive XML is inventoried
and checksum-checked against the archive, but excluded from the domain model
as required by task.pdf. Run from anywhere; inputs are never modified.
"""

from collections import Counter, defaultdict
from io import BytesIO
import json
from pathlib import Path
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile
import zlib


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "docs" / "data-profile.json"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
O = "{http://zakupki.gov.ru/oos/types/1}"


def local(tag):
    return tag.rsplit("}", 1)[-1]


def txt(element, path):
    return element.findtext("/".join(O + part for part in path.split("/")), "")


def nodes(element, path):
    return element.findall("/".join(O + part for part in path.split("/")))


def normalize(value):
    return " ".join(value.casefold().replace("ё", "е").split())


def sample_row(number, row):
    return {"row": number, "values": {k: v[:500] + ("… [truncated sample]" if len(v) > 500 else "") for k, v in row.items()}}


def workbook_rows(path):
    with ZipFile(path) as book:
        strings = []
        if "xl/sharedStrings.xml" in book.namelist():
            with book.open("xl/sharedStrings.xml") as source:
                for _, element in ET.iterparse(source, events=("end",)):
                    if element.tag == S + "si":
                        strings.append("".join(n.text or "" for n in element.iter(S + "t")))
                        element.clear()
        rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        targets = {e.get("Id"): e.get("Target") for e in rels}
        workbook = ET.fromstring(book.read("xl/workbook.xml"))
        for sheet in workbook.find(S + "sheets"):
            target = targets[sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")]
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            with book.open(target) as source:
                for _, element in ET.iterparse(source, events=("end",)):
                    if element.tag != S + "row":
                        continue
                    values = {}
                    for cell in element:
                        if cell.tag != S + "c":
                            continue
                        value = cell.findtext(S + "v", "")
                        if cell.get("t") == "s" and value:
                            value = strings[int(value)]
                        elif cell.get("t") == "inlineStr":
                            value = "".join(n.text or "" for n in cell.iter(S + "t"))
                        if value:
                            values[re.sub(r"\d", "", cell.get("r"))] = value
                    yield sheet.get("name"), int(element.get("r")), values
                    element.clear()


def profile_workbooks():
    profiles, ids_by_book = {}, {}
    all_names, reference_ids = set(), set()
    for path in sorted(DATA.rglob("*.xlsx")):
        sheets = {}
        ids = Counter()
        categories = defaultdict(set)
        code_categories = defaultdict(set)
        definitions = defaultdict(set)
        references = defaultdict(set)
        row_counts = Counter()
        prop_names, units = set(), set()
        raw_tokens = 0
        for sheet, row_number, row in workbook_rows(path):
            if sheet not in sheets:
                sheets[sheet] = {"header": row, "rows": 0, "nonempty_by_column": Counter(), "samples": [], "extra_column_samples": []}
                continue
            if not row:
                continue
            p = sheets[sheet]
            p["rows"] += 1
            p["nonempty_by_column"].update(row.keys())
            if len(p["samples"]) < 2:
                p["samples"].append(sample_row(row_number, row))
            extra = {k: v for k, v in row.items() if k not in p["header"]}
            if extra and len(p["extra_column_samples"]) < 3:
                p["extra_column_samples"].append(sample_row(row_number, extra))
            if p["header"].get("A") == "ID СТЕ":
                ids[row.get("A", "")] += 1
                raw_tokens += len(row["F"].split(" | ")) if row.get("F") else 0
                for field, marker in (("F", "(не задано)"), ("F", "0.00000")):
                    p.setdefault("marker_rows", Counter())[marker] += marker in row.get(field, "")
            else:
                if (not re.fullmatch(r"\d{2}(?:\.\d{2})+", row.get("B", ""))
                        or row.get("E") not in {"Базовая", "Эталонная", "Категореобразующая"}
                        or not row.get("D") or not row.get("F")):
                    p.setdefault("malformed_rows", []).append(row_number)
                    if len(p.setdefault("malformed_samples", [])) < 3:
                        p["malformed_samples"].append(sample_row(row_number, row))
                    continue
                p["structurally_valid_rows"] = p.get("structurally_valid_rows", 0) + 1
                p["unresolved_value_marker_rows"] = p.get("unresolved_value_marker_rows", 0) + ("[не найдено значение ID:" in row.get("G", ""))
                categories[row.get("A", "")].add(row.get("B", ""))
                code_categories[row.get("B", "")].add(row.get("A", ""))
                definitions[(row.get("A", ""), row.get("D", ""))].add(tuple(row.get(k, "") for k in "BEFHIJ"))
                row_counts[tuple(row.get(k, "") for k in "ABCDEFGHIJK")] += 1
                prop_names.add(row.get("D", ""))
                if row.get("H"):
                    units.add(row["H"])
                if row.get("I"):
                    ref_ids = [v.strip() for v in row["I"].split("|")]
                    ref_names = [v.strip() for v in row.get("J", "").split("|")]
                    if len(ref_ids) != len(ref_names):
                        p.setdefault("spgz_id_name_length_mismatch_rows", []).append(row_number)
                    for ref_id, ref_name in zip(ref_ids, ref_names):
                        references[ref_id].add(ref_name)
                        reference_ids.add(ref_id)
                    p["spgz_reference_edges"] = p.get("spgz_reference_edges", 0) + len(ref_ids)
                    if len(p.setdefault("spgz_samples", [])) < 3:
                        p["spgz_samples"].append(sample_row(row_number, row))
                p.setdefault("role_counts", Counter())[row.get("E", "<empty>")] += 1
                p.setdefault("type_counts", Counter())[row.get("F", "<empty>")] += 1
        ids_by_book[path.stem] = set(ids) - {""}
        all_names.update(prop_names)
        profiles[path.stem] = {
            "path": str(path.relative_to(ROOT)), "sheets": sheets,
            "unique_ste_ids": len(ids_by_book[path.stem]),
            "duplicate_ste_ids": {k: v for k, v in ids.items() if v > 1},
            "raw_characteristic_segments": raw_tokens,
            "categories": len(categories), "kpgz_codes": len(code_categories),
            "category_to_kpgz": {k: sorted(v) for k, v in categories.items()},
            "kpgz_with_multiple_categories": {k: sorted(v) for k, v in code_categories.items() if len(v) > 1},
            "category_property_pairs": len(definitions),
            "category_property_pairs_with_multiple_definitions": sum(len(v) > 1 for v in definitions.values()),
            "duplicate_template_rows": sum(v - 1 for v in row_counts.values()),
            "property_name_count": len(prop_names), "property_name_samples": sorted(prop_names)[:30], "unit_labels": sorted(units),
            "spgz_reference_ids": len(references),
            "spgz_ids_with_multiple_names": {k: sorted(v) for k, v in references.items() if len(v) > 1},
        }
        print(f"Workbook {path.stem}: {len(ids_by_book[path.stem])} STE IDs, {len(categories)} categories", flush=True)
    overlaps = {}
    for a, a_ids in ids_by_book.items():
        for b, b_ids in ids_by_book.items():
            if a < b:
                overlap = a_ids & b_ids
                overlaps[f"{a} / {b}"] = {"count": len(overlap), "sample": sorted(overlap)[:5]}
    return profiles, overlaps, all_names, reference_ids


def profile_ktru(property_names, reference_ids):
    counts, paths, fields = Counter(), Counter(), defaultdict(Counter)
    positions, code_versions = {}, defaultdict(list)
    char_names, char_codes, value_codes = set(), defaultdict(set), Counter()
    okei, rubrics, classifiers = defaultdict(set), defaultdict(set), Counter()
    parents, examples, duplicate_records = [], {}, []
    per_file = []
    for index, path in enumerate(sorted(DATA.rglob("*all_actual*.xml")), 1):
        file_count = 0
        stack = []
        for event, element in ET.iterparse(path, events=("start", "end")):
            if event == "start":
                stack.append(element)
                continue
            if element.tag != O + "position":
                stack.pop()
                continue
            data = element.find(O + "data")
            code, version = txt(data, "code"), txt(data, "version")
            key = code + "@" + version
            counts["positions"] += 1
            file_count += 1
            counts["duplicate_code_version"] += key in positions
            if key in positions:
                duplicate_records.append({"key": key, "previous_file": positions[key]["file"], "file": path.name})
            positions[key] = {"code": code, "version": version, "name": txt(data, "name"), "template": txt(data, "isTemplate"), "versionCode": txt(data, "versionCode"), "status": txt(data, "status"), "file": path.name}
            if txt(data, "status") == "ACTIVE":
                counts["active_templates" if txt(data, "isTemplate") == "true" else "active_non_templates"] += 1
                counts["active_with_parent"] += data.find(O + "parentPositionInfo") is not None
                counts["active_without_characteristics"] += not nodes(data, "characteristics/characteristic")
            code_versions[code].append(version)
            for child in data:
                field = local(child.tag)
                counts["field:" + field] += 1
                if field in ("status", "isTemplate", "noNewFeatures", "actual"):
                    fields[field][child.text or ""] += 1
            def walk(node, prefix="data"):
                paths[prefix] += 1
                for child in node:
                    walk(child, prefix + "/" + local(child.tag))
            walk(data)
            for unit in data.iter(O + "OKEI"):
                okei[txt(unit, "code")].add(txt(unit, "name"))
            for rubric in nodes(data, "rubricators/rubricatorInfo"):
                rubrics[txt(rubric, "code")].add(txt(rubric, "name"))
            for classifier in nodes(data, "NSI/classifiers/classifier"):
                classifiers[txt(classifier, "NSIcode") + ":" + txt(classifier, "code")] += 1
            parent = data.find(O + "parentPositionInfo")
            if parent is not None:
                parents.append((key, txt(parent, "code") + "@" + txt(parent, "version")))
            current_char_codes = []
            for char in nodes(data, "characteristics/characteristic"):
                counts["characteristics"] += 1
                cc, name = txt(char, "code"), txt(char, "name")
                char_names.add(name)
                char_codes[cc].add(name)
                current_char_codes.append(cc)
                for field in ("type", "kind", "actual", "isRequired", "choiceType"):
                    fields["characteristic:" + field][txt(char, field) or "<missing>"] += 1
                current_value_codes = []
                for value in nodes(char, "values/value"):
                    counts["values"] += 1
                    vc = txt(value, "valueCode")
                    value_codes[vc] += 1
                    current_value_codes.append(vc)
                    fields["value:valueFormat"][txt(value, "valueFormat") or "<missing>"] += 1
                counts["characteristics_with_duplicate_value_codes"] += len(current_value_codes) != len(set(current_value_codes))
            counts["positions_with_duplicate_characteristic_codes"] += len(current_char_codes) != len(set(current_char_codes))
            for domain, prefix in (("clothing", "14."), ("furniture", "31."), ("tools", "28.24.")):
                if code.startswith(prefix):
                    counts["prefix:" + prefix] += 1
                    if domain not in examples and nodes(data, "characteristics/characteristic") and txt(data, "isTemplate") == "false" and txt(data, "status") == "ACTIVE":
                        examples[domain] = {"file": path.name, "xml": ET.tostring(data, encoding="unicode")}
            if "template" not in examples and txt(data, "isTemplate") == "true":
                examples["template"] = {"file": path.name, "xml": ET.tostring(data, encoding="unicode")}
            for relation in ("products", "nsiDescription", "attachments", "cancelInfo"):
                if relation not in examples and data.find(O + relation) is not None:
                    examples[relation] = {"file": path.name, "xml": ET.tostring(data.find(O + relation), encoding="unicode")[:16000]}
            stack[-2].remove(element)
            stack.pop()
        per_file.append({"file": str(path.relative_to(ROOT)), "positions": file_count})
        if index % 10 == 0:
            print(f"Active XML: {index} files, {counts['positions']} positions", flush=True)
    missing = [(c, p) for c, p in parents if p not in positions]
    active_missing = [(c, p) for c, p in missing if positions[c]["status"] == "ACTIVE"]
    norm_ktru = {normalize(n) for n in char_names}
    return {
        "counts": counts, "field_values": fields, "xml_paths": paths, "files": per_file,
        "unique_codes": len(code_versions), "unique_code_versions": len(positions),
        "unique_version_codes": len({p["versionCode"] for p in positions.values()} - {""}),
        "codes_with_multiple_records": {k: v for k, v in code_versions.items() if len(v) > 1},
        "duplicate_record_sources": duplicate_records,
        "unique_characteristic_codes": len(char_codes), "unique_characteristic_names": len(char_names),
        "characteristic_codes_with_multiple_names": {k: sorted(v) for k, v in char_codes.items() if len(v) > 1},
        "unique_value_codes": len(set(value_codes) - {""}),
        "reused_value_codes": sum(v > 1 for code, v in value_codes.items() if code),
        "parent_edges": len(parents), "unresolved_parent_versions": len(missing), "unresolved_parent_samples": missing[:10],
        "unresolved_parent_codes": sum(p.rsplit("@", 1)[0] not in code_versions for _, p in missing),
        "active_unresolved_parent_versions": len(active_missing),
        "active_unresolved_parent_codes": sum(p.rsplit("@", 1)[0] not in code_versions for _, p in active_missing),
        "parents_not_templates": sum(p in positions and positions[p]["template"] != "true" for _, p in parents),
        "okei": {k: sorted(v) for k, v in okei.items()}, "rubricators": {k: sorted(v) for k, v in rubrics.items()},
        "classifier_counts": classifiers,
        "excel_property_name_overlap_count": sum(normalize(n) in norm_ktru for n in property_names),
        "excel_property_name_overlap_samples": sorted(n for n in property_names if normalize(n) in norm_ktru)[:30],
        "excel_property_name_count": len(property_names),
        "excel_spgz_ids_equal_ktru_characteristic_codes": len(reference_ids & set(char_codes)),
        "examples": examples,
    }


def inventory():
    result = []
    for path in sorted(DATA.rglob("*")):
        if not path.is_file():
            continue
        role = "supporting_document"
        if "all_not-actual" in path.name:
            role = "inactive_ktru_excluded_by_task"
        elif "all_actual" in path.name:
            role = "active_ktru"
        elif path.suffix == ".xlsx":
            role = "portal_export"
        elif path.suffix == ".zip":
            role = "archive_copy"
        elif path.name == ".gitkeep":
            role = "placeholder"
        result.append({"file": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "role": role})
    return result


def check_archive():
    result = {"nested_archives": 0, "matched_extracted_xml": 0, "mismatches": []}
    archive = DATA / "КТРУ" / "КТРУ xml.zip"
    extracted = {p.name: p for p in DATA.rglob("*.xml")}
    with ZipFile(archive) as outer:
        for item in outer.infolist():
            if item.is_dir():
                continue
            result["nested_archives"] += 1
            with ZipFile(BytesIO(outer.read(item))) as inner:
                for info in inner.infolist():
                    if info.is_dir():
                        continue
                    path = extracted.get(Path(info.filename).name)
                    crc = 0
                    if path is not None:
                        with path.open("rb") as source:
                            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                                crc = zlib.crc32(chunk, crc)
                    if path is not None and path.stat().st_size == info.file_size and crc == info.CRC:
                        result["matched_extracted_xml"] += 1
                    else:
                        result["mismatches"].append(info.filename)
    return result


def main():
    books, overlaps, names, refs = profile_workbooks()
    result = {"scope": "All workbook rows; all active XML; inactive XML excluded from semantic analysis per task.pdf", "inventory": inventory(), "workbooks": books, "ste_id_overlaps": overlaps}
    result["ktru"] = profile_ktru(names, refs)
    print("Checking archive against extracted XML files", flush=True)
    result["archive"] = check_archive()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"Saved {OUT}", flush=True)


if __name__ == "__main__":
    main()
