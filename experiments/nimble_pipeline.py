"""Explainable raw-text -> KTRU shortlist experiment using the existing Nimble API.

This is an exploratory constraint check, not a final-code validator. It cannot
extract arbitrary unseen text properties or establish full catalog eligibility.
Use --dry-run to inspect requests, or --replay to inspect saved inference offline.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re

if __package__:
    from . import nimble_experiments as ne
else:
    import nimble_experiments as ne


STOP_WORDS = {"нужен", "нужна", "нужно", "нужны", "товар", "поставить", "купить", "для", "без", "с", "и", "из", "от", "на"}
SUFFIXES = ("иями", "ами", "ого", "ему", "ому", "ыми", "ими", "ая", "яя", "ое", "ее", "ые", "ие", "ый", "ий", "ой", "ов", "ей", "ам", "ям", "ах", "ях", "ы", "и", "а", "я", "у", "ю", "е", "ь")


def tokens(text):
    """Small, inspectable lexical baseline; no morphology/embedding claims."""
    result = set()
    for token in re.findall(r"[а-яa-z]+", ne.normalize(text)):
        if token in STOP_WORDS or len(token) < 3:
            continue
        for suffix in SUFFIXES:
            if token.endswith(suffix) and len(token) - len(suffix) >= 4:
                token = token[:-len(suffix)]
                break
        result.add(token)
    return result


def retrieve(catalog, text, scope="all", top_k=8):
    positions = ne.select_scope(catalog, scope)
    # Keep accessory/negated-property words out of object-name retrieval.
    product_phrase = re.split(r"[;|\n]|\s+(?:без|с|со|из|для)\s+", text, maxsplit=1, flags=re.I)[0]
    query = tokens(product_phrase)
    vocabulary = [tokens(p["name"]) for p in positions]
    frequencies = Counter(token for words in vocabulary for token in words)
    ranked = []
    for position, words in zip(positions, vocabulary):
        shared = query & words
        if not shared:
            continue
        score = sum(math.log(1 + len(positions) / frequencies[t]) for t in shared) / math.sqrt(len(words))
        ranked.append((score, position["key"], position, sorted(shared)))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    # Several versions/codes of one name must not consume the entire shortlist.
    # Preserve identities; diversify the order rather than merging records.
    groups = defaultdict(list)
    for row in ranked:
        groups[ne.normalize(row[2]["name"])].append(row)
    diversified = []
    depth = 0
    while len(diversified) < min(top_k, len(ranked)):
        for group in groups.values():
            if depth < len(group) and len(diversified) < top_k:
                diversified.append(group[depth])
        depth += 1
    return {
        "positions": [row[2] for row in diversified],
        "evidence": [{"key": row[1], "score": round(row[0], 6), "shared_tokens": row[3]} for row in diversified],
        "scope_positions": len(positions), "lexical_matches": len(ranked),
        "truncated": len(ranked) > top_k,
        "product_phrase": product_phrase,
        "note": "Name-only lexical shortlist, diversified across distinct names before inference. Recall is not measured; an empty shortlist is a retrieval miss, not proof of no KTRU match.",
    }


def scalar_span(span, text):
    """Do not convert a signed number, bound or range endpoint into a point."""
    left = text[:span["start"]]
    right = text[span["end"]:]
    clause = re.split(r"[;|\n]", left)[-1] + span["raw"] + re.split(r"[;|\n]", right)[0]
    return not (
        re.search(r"[-−<>≤≥≈±]\s*$", left)
        or re.match(r"\s*[-–—±]\s*\d", right)
        or re.search(r"\d\s*[-–—]\s*\d|не\s+(?:менее|более)|(?:от|до)\s+\d|[<>≤≥≈±]", clause, re.I)
    )


def prepare(catalog, text, scope="all", top_k=8, chunk_size=4, max_questions=128):
    retrieval = retrieve(catalog, text, scope, top_k)
    facts = sorted(ne.family_facts(catalog, retrieval["positions"]), key=lambda f: f["id"])
    jobs = []
    for name in sorted({p["name"] for p in retrieval["positions"]}):
        qid = "product_" + ne.identity(name)
        question = ne.fact_question({"name": "Вид самого товара", "value": name})
        jobs.append({"id": qid, "experiment": "pipeline_product", "product_name": name,
                     "body": ne.request_body(text, {qid: question})})
    for offset in range(0, len(facts), chunk_size):
        chunk = facts[offset:offset + chunk_size]
        jobs.append({"id": f"categorical_{offset}", "experiment": "pipeline_facts", "facts": chunk,
                     "body": ne.request_body(text, {f["id"]: ne.fact_question(f) for f in chunk})})
    spans = ne.measurements(text)
    numerical = {}
    for position in retrieval["positions"]:
        for char in position["characteristics"]:
            if char["type"] != "2":
                continue
            for entry in char["values"]:
                key = (ne.normalize(char["name"]), entry["unit_code"])
                numerical.setdefault(key, {"name": char["name"], "okei": entry["unit_code"]})
    for key, char in sorted(numerical.items()):
        candidates = [s for s in spans if s["okei"] == char["okei"] and scalar_span(s, text)]
        if not candidates:
            continue
        if len(candidates) > 253:
            raise ValueError("Too many numeric spans for a choice question; shorten the input")
        qid = "measurement"
        criteria = {s["id"]: f"Фрагмент {s['raw']} (позиции {s['start']}:{s['end']}) явно задает '{char['name']}' самого товара; нормализованное значение {s['value']}, ОКЕИ {s['okei']}." for s in candidates}
        criteria.update(unknown="Свойство не указано. Числа упаковки, аксессуаров и других объектов не подходят.",
                        conflicting="Для одного свойства товара одновременно указаны несовместимые значения, ни одно не отменено.")
        question = {"type": "choice", "instructions": f"Выбери точное числовое значение свойства '{char['name']}' самого товара. Учитывай контекст и исправления. Не подставляй число только из-за совпадения единицы измерения.", "criteria": criteria}
        jobs.append({"id": "binding_" + ne.identity(*key), "experiment": "pipeline_numeric",
                     "numeric_property": char, "spans": candidates, "binding_question": qid,
                     "body": ne.request_body(text, {qid: question})})
    questions = sum(len(j["body"]["questions"]) for j in jobs)
    if questions > max_questions:
        raise ValueError(f"Shortlist requires {questions} questions, above --max-questions={max_questions}; reduce --top-k or inspect a narrower --scope")
    return {"text": text, "catalog_sha256": hashlib.sha256(json.dumps(catalog, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "retrieval": retrieval, "facts": facts, "spans": spans,
            "jobs": jobs, "question_count": questions}


def numeric_rule(value, entry):
    """True/False/None for a catalog value alternative; preserve open bounds."""
    try:
        value = Decimal(value)
        if not value.is_finite():
            return None
        outcomes = []
        for exact in entry.get("exact", []):
            outcomes.append(value == Decimal(exact))
        for interval in entry.get("ranges", []):
            checks = []
            for bound, operations in (
                ("min", {"greater": lambda x, y: x > y, "greaterOrEqual": lambda x, y: x >= y}),
                ("max", {"less": lambda x, y: x < y, "lessOrEqual": lambda x, y: x <= y}),
            ):
                if not interval.get(bound):
                    continue
                operation = operations.get(interval.get(bound + "MathNotation"))
                checks.append(operation(value, Decimal(interval[bound])) if operation else None)
            outcomes.append(False if False in checks else None if not checks or None in checks else True)
        return True if True in outcomes else None if not outcomes or None in outcomes else False
    except (InvalidOperation, TypeError):
        return None


def analyze(plan, records, threshold=0.8, confirmed_extras=()):
    facts = plan["facts"]
    answers = {qid: answer for r in records for qid, answer in r.get("response", {}).get("answers", {}).items() if qid in {f["id"] for f in facts}}
    extracted = [dict(f, status=answers[f["id"]]["choice"], probabilities=answers[f["id"]]["probabilities"],
                      accepted=answers[f["id"]]["choice"] == "supported" and answers[f["id"]]["probabilities"]["supported"] >= threshold,
                      evidence_span=None, evidence_note="Model classification; no verified categorical source span.") for f in facts if f["id"] in answers]
    bindings = defaultdict(list)
    unresolved = []
    product_answers = {}
    for record in records:
        if record.get("experiment") == "pipeline_product" and "response" in record:
            product_answers[record["product_name"]] = record["response"]["answers"].get(record["id"])
    for record in records:
        if record.get("experiment") != "pipeline_numeric" or "response" not in record:
            continue
        prop = record["numeric_property"]
        answer = record["response"]["answers"][record["binding_question"]]
        span = next((s for s in record["spans"] if s["id"] == answer["choice"]), None)
        if span and answer["probabilities"][answer["choice"]] >= threshold:
            bindings[(ne.normalize(prop["name"]), prop["okei"])].append(span)
        elif answer["choice"] == "conflicting":
            unresolved.append({"name": prop["name"], "reason": "conflicting numeric values"})
    categorical = ne.narrow_candidates(plan["retrieval"]["positions"], facts, records, threshold)
    by_key = {(c["code"], c["version"]): c for c in categorical}
    candidates = []
    bound_ids = set()
    for position in plan["retrieval"]["positions"]:
        candidate = dict(by_key[(position["code"], position["version"])])
        candidate.update(key=position["key"], source=position["source"], numeric_checks=[], missing_required=[], extra_characteristics=[])
        product_answer = product_answers.get(position["name"])
        candidate["product_relevance"] = product_answer
        candidate["object_supported"] = bool(product_answer and product_answer["choice"] == "supported" and product_answer["probabilities"]["supported"] >= threshold)
        if product_answer and product_answer["choice"] == "contradicted" and product_answer["probabilities"]["contradicted"] >= threshold:
            candidate["compatible"] = False
        matched_names = {ne.normalize(f["name"]) for f in facts if f["id"] in candidate["matches"]}
        for char in position["characteristics"]:
            name = ne.normalize(char["name"])
            covered = name in matched_names
            if char["type"] == "2":
                for unit in {v["unit_code"] for v in char["values"]}:
                    for span in bindings.get((name, unit), []):
                        alternatives = [numeric_rule(span["value"], v) for v in char["values"] if v["unit_code"] == unit]
                        status = "matched" if True in alternatives else "uncertain" if not alternatives or None in alternatives else "conflict"
                        candidate["numeric_checks"].append({"name": char["name"], "characteristic_code": char["code"], "span": span, "status": status})
                        bound_ids.add(span["id"])
                        covered |= status == "matched"
                        candidate["compatible"] &= status != "conflict"
            if char["required"] and not covered:
                candidate["missing_required"].append({"name": char["name"], "type": char["type"], "characteristic_code": char["code"]})
        for extra in confirmed_extras:
            known = any(ne.normalize(c["name"]) == ne.normalize(extra["name"]) for c in position["characteristics"])
            action = ("map_and_validate" if known else "do_not_add" if position["no_new_features"] == "true"
                      else "review_before_add" if position["no_new_features"] == "false" else "additional_field_policy_unknown")
            candidate["extra_characteristics"].append(dict(extra, action=action))
        candidate["lifecycle_review_required"] = True
        candidate["assessment"] = (
            "rejected" if not candidate["compatible"] else
            "uncertain" if not candidate["object_supported"] or candidate["uncertain"]
            or any(check["status"] == "uncertain" for check in candidate["numeric_checks"]) else
            "supported"
        )
        candidates.append(candidate)
    job_ids = {r["id"] for r in records if "response" in r}
    complete = all(j["id"] in job_ids for j in plan["jobs"])
    survivors = [c for c in candidates if c["compatible"]]
    supported = [c for c in candidates if c["assessment"] == "supported"]
    conflicts = [f for f in extracted if f["status"] == "conflicting"]
    uncertain = [c for c in survivors if c["uncertain"]]
    object_uncertain = [c for c in survivors if not c["object_supported"]]
    if not candidates:
        status = "retrieval_miss"
        question = "Уточните наименование и назначение товара: лексический поиск не нашёл кандидатов."
    elif not complete:
        status = "incomplete_inference"
        question = "Завершите проверку характеристик: отсутствующие ответы нельзя считать отрицанием."
    elif not survivors:
        status = "no_compatible_shortlist_candidate"
        question = "Проверьте указанные противоречия; также может потребоваться расширить поиск кандидатов."
    elif conflicts or unresolved or uncertain:
        status = "needs_clarification"
        question = "Уточните противоречивые характеристики перед исключением кандидатов."
    elif supported:
        status = "needs_clarification" if len(supported) > 1 or any(c["missing_required"] for c in supported) else "ready_for_review"
        question = clarification(plan, supported, extracted) if status == "needs_clarification" else None
    elif object_uncertain:
        status = "needs_clarification"
        question = "Уточните вид самого товара: выберите или уточните " + "; ".join(sorted({c["name"] for c in object_uncertain})) + "."
    else:
        status = "needs_clarification"
        question = clarification(plan, survivors, extracted)
    return {
        "status": status, "final_code": None,
        "provisional_candidate": supported[0]["code"] if len(supported) == 1 and complete and not (conflicts or unresolved or uncertain) else None,
        "input": plan["text"], "retrieval": {k: v for k, v in plan["retrieval"].items() if k != "positions"},
        "complete_inference": complete, "threshold_uncalibrated": threshold,
        "categorical_facts": extracted, "numeric_bindings": [{"name": name, "okei": unit, "spans": spans} for (name, unit), spans in bindings.items()],
        "unbound_measurements": [s for s in plan["spans"] if s["id"] not in bound_ids],
        "unresolved_numeric": unresolved, "candidates": candidates, "clarifying_question": question,
        "limits": ["Exploratory rubric/prefix catalog coverage, not all KTRU.",
                   "Lexical retrieval recall and categorical source spans are not validated.",
                   "Only supported point measurements and units are bound; ranges require review.",
                   "Arbitrary extra properties are not generated. --extra preserves user-supplied fields.",
                   "Lifecycle, semantic relevance and remaining application rules require review; no final code is issued."],
    }


def clarification(plan, survivors, extracted):
    positions = {p["key"]: p for p in plan["retrieval"]["positions"]}
    known_names = {ne.normalize(f["name"]) for f in extracted if f["accepted"]}
    options = defaultdict(dict)
    for candidate in survivors:
        for char in positions[candidate["key"]]["characteristics"]:
            if char["type"] == "1" and ne.normalize(char["name"]) not in known_names:
                values = tuple(sorted({v["text"] for v in char["values"] if v["text"]}))
                if values:
                    options[char["name"]][candidate["key"]] = values
    for name, per_candidate in sorted(options.items()):
        if len(per_candidate) == len(survivors) and len(set(per_candidate.values())) > 1:
            choices = sorted({v for values in per_candidate.values() for v in values})
            return f"Уточните '{name}': " + ", ".join(choices) + "."
    missing = Counter(c["name"] for candidate in survivors for c in candidate["missing_required"])
    if missing:
        name = sorted(missing, key=lambda n: (-missing[n], n))[0]
        units = sorted({ne.UNIT_SYMBOLS.get(v["unit_code"], v.get("unit_name", "")) for candidate in survivors
                        for char in positions[candidate["key"]]["characteristics"] if char["name"] == name
                        for v in char["values"] if v["unit_code"] in ne.UNIT_SYMBOLS or v.get("unit_name")})
        return f"Укажите «{name}»" + (f" ({', '.join(units)})." if units else ".")
    if len(survivors) > 1:
        return "Уточните вид и назначение товара: " + "; ".join(sorted({c["name"] for c in survivors})) + "."
    return "Подтвердите извлечённые характеристики и проверьте применимость позиции; эксперимент ещё не выдаёт окончательный код."


def replay(plan, directories):
    """Reuse only identical request questions and input text; never relabel output."""
    saved = []
    for directory in directories:
        manifest_path = directory / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            if manifest.get("catalog_sha256") and manifest["catalog_sha256"] != plan["catalog_sha256"]:
                raise ValueError(f"Catalog snapshot differs from saved run: {directory}")
        path = directory / "requests.jsonl"
        saved.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    records = []
    for job in plan["jobs"]:
        answers = {}
        sources = []
        for record in saved:
            request = record.get("request", {})
            if request.get("state") != plan["text"] or request.get("model") != ne.MODEL or "response" not in record or record["response"].get("model") != ne.MODEL:
                continue
            for qid, question in job["body"]["questions"].items():
                if request.get("questions", {}).get(qid) == question and qid in record["response"]["answers"]:
                    answers[qid] = record["response"]["answers"][qid]
                    sources.append(record["id"])
        if answers:
            result = {k: v for k, v in job.items() if k != "body"}
            result.update(request=job["body"], response={"model": ne.MODEL, "answers": answers}, replay_source_ids=sorted(set(sources)))
            # A partial chunk is useful evidence but does not mark a job complete.
            if set(answers) != set(job["body"]["questions"]):
                result["id"] += "_partial"
            records.append(result)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True)
    parser.add_argument("--scope", choices=("all", "drills", "tools", "clothing", "furniture"), default="all")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--chunk-size", type=int, default=4)
    parser.add_argument("--max-questions", type=int, default=128)
    parser.add_argument("--threshold", type=float, default=.8)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--base-url", default="http://127.0.0.1:8769")
    parser.add_argument("--catalog-cache", type=Path, default=ne.ROOT / "experiments/results/nimble_catalog.json")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--replay", type=Path, action="append", default=[])
    parser.add_argument("--extra", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.text.strip() or min(args.top_k, args.chunk_size, args.max_questions) < 1 or not 0 <= args.threshold <= 1 or args.timeout <= 0:
        parser.error("text must be nonempty; limits and timeout positive; threshold in [0,1]")
    extras = []
    for raw in args.extra:
        name, separator, value = raw.partition("=")
        if not separator or not name.strip() or not value.strip():
            parser.error("--extra must be NAME=VALUE with both fields nonempty")
        extras.append({"name": name.strip(), "value": value.strip(), "origin": "user_supplied"})
    catalog = json.loads(args.catalog_cache.read_text()) if args.catalog_cache.exists() else ne.load_catalog()
    try:
        plan = prepare(catalog, args.text, args.scope, args.top_k, args.chunk_size, args.max_questions)
    except ValueError as error:
        parser.error(str(error))
    if args.dry_run:
        print(json.dumps({"mode": "dry_run", "requests": len(plan["jobs"]), "questions": plan["question_count"],
                          "analysis": analyze(plan, [], args.threshold, extras),
                          "first_request": plan["jobs"][0]["body"] if plan["jobs"] else None}, ensure_ascii=False, indent=2))
        return 0
    output = args.output or ne.ROOT / "experiments/results" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_pipeline")
    if args.replay or not plan["jobs"]:
        try:
            records = replay(plan, args.replay) if args.replay else []
        except (OSError, ValueError) as error:
            parser.error(str(error))
        output.mkdir(parents=True, exist_ok=False)
    else:
        try:
            records, _ = ne.run_jobs(ne.SystemOneClient(args.base_url, args.timeout), plan["jobs"], output, catalog, args.threshold, args.scope)
        except (RuntimeError, ValueError) as error:
            print(str(error))
            return 1
    report = analyze(plan, records, args.threshold, extras)
    report.update(mode="replay" if args.replay else "live", replay_sources=[str(p) for p in args.replay],
                  catalog_sha256=hashlib.sha256(json.dumps(catalog, ensure_ascii=False, sort_keys=True).encode()).hexdigest())
    (output / "analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (output / "request_plan.json").write_text(json.dumps(plan["jobs"], ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "mode": report["mode"], "complete_inference": report["complete_inference"],
                      "retrieved": len(report["candidates"]), "compatible": sum(c["compatible"] for c in report["candidates"]),
                      "provisional_candidate": report["provisional_candidate"], "final_code": report["final_code"],
                      "clarifying_question": report["clarifying_question"], "report": str(output / "analysis.json")}, ensure_ascii=False, indent=2))
    return int(any("error" in r for r in records))


if __name__ == "__main__":
    raise SystemExit(main())
