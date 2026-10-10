"""Catalog experiments for the team's loopback Nimble System One API.

Standard-library client and data preparation; no model is loaded locally.
Run --dry-run before forwarding localhost:8769. Live runs are opt-in.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
MODEL = "bespokelabs/Bespoke-Nimble-9B-v3"
NS = "{http://zakupki.gov.ru/oos/types/1}"
STATUSES = {
    "supported": "Описание явно подтверждает факт, включая однозначные синонимы.",
    "contradicted": "Описание явно отрицает факт или прямо указывает несовместимое значение.",
    "unknown": "Для проверки факта недостаточно данных. Отсутствие упоминания не означает отрицание.",
    "conflicting": "В описании есть одновременно подтверждение и отрицание этого факта.",
}


def normalize(text):
    return " ".join(text.casefold().replace("ё", "е").split())


def identity(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:20]


def xml_text(element, path):
    return element.findtext("/".join(NS + part for part in path.split("/")), "")


def load_catalog(data_dir=ROOT / "data"):
    """Explicit exploratory domains; not a complete workbook-to-KTRU crosswalk.

    ACTIVE non-template records are retained with dates for review. No inferred
    lifecycle policy or fallback to a different parent version is applied.
    """
    positions, facts = {}, {}
    paths = sorted(Path(data_dir).rglob("*all_actual*.xml"))
    if not paths:
        raise FileNotFoundError(f"No actual KTRU XML under {data_dir}")
    for path in paths:
        stack = []
        for event, element in ET.iterparse(path, events=("start", "end")):
            if event == "start":
                stack.append(element)
                continue
            if element.tag != NS + "position":
                stack.pop()
                continue
            data = element.find(NS + "data")
            code = xml_text(data, "code")
            rubrics = {xml_text(r, "code") for r in data.findall(NS + "rubricators/" + NS + "rubricatorInfo")}
            domains = []
            if "116" in rubrics:
                domains.append("clothing")
            if "128" in rubrics:
                domains.append("furniture")
            if code.startswith(("25.73.", "28.24.")):
                domains.append("tools")
            if domains and xml_text(data, "status") == "ACTIVE" and xml_text(data, "isTemplate") == "false":
                version = xml_text(data, "version")
                key = f"{code}@{version}"
                position = {
                    "key": key, "code": code, "version": version,
                    "name": xml_text(data, "name"), "domains": domains,
                    "source": str(path.relative_to(Path(data_dir))),
                    "application_start": xml_text(data, "applicationDateStart"),
                    "application_end": xml_text(data, "applicationDateEnd"),
                    "no_new_features": xml_text(data, "noNewFeatures"),
                    "characteristics": [],
                }
                for char in data.findall(NS + "characteristics/" + NS + "characteristic"):
                    if xml_text(char, "actual") == "false":
                        continue
                    characteristic = {
                        "code": xml_text(char, "code"), "name": xml_text(char, "name"),
                        "type": xml_text(char, "type"), "kind": xml_text(char, "kind"),
                        "required": xml_text(char, "isRequired") == "true", "values": [],
                    }
                    for ordinal, value in enumerate(char.findall(NS + "values/" + NS + "value")):
                        entry = {
                            "ordinal": ordinal, "code": xml_text(value, "valueCode"),
                            "text": xml_text(value, "qualityDescription"),
                            "unit_code": xml_text(value, "OKEI/code"),
                            "unit_name": xml_text(value, "OKEI/name"),
                            "ranges": [], "exact": [],
                        }
                        for interval in value.findall(NS + "rangeSet/" + NS + "valueRange"):
                            entry["ranges"].append({name: xml_text(interval, name) for name in ("min", "max", "minMathNotation", "maxMathNotation")})
                        entry["exact"] = [n.text for n in value.findall(NS + "valueSet/" + NS + "concreteValue")]
                        characteristic["values"].append(entry)
                    position["characteristics"].append(characteristic)
                if key in positions and positions[key] != position:
                    raise ValueError(f"Conflicting duplicate position {key}")
                positions[key] = position
            stack[-2].remove(element)
            element.clear()
            stack.pop()
    for position in positions.values():
        for char in position["characteristics"]:
            for value in char["values"]:
                if not value["text"]:
                    continue
                fid = identity(normalize(char["name"]), normalize(value["text"]), value["unit_code"])
                fact = facts.setdefault(fid, {
                    "id": fid, "name": char["name"], "value": value["text"],
                    "unit_code": value["unit_code"], "sources": [],
                })
                fact["sources"].append({"position": position["key"], "characteristic_code": char["code"], "value_ordinal": value["ordinal"]})
    return {"positions": list(positions.values()), "facts": list(facts.values()), "xml_files": len(paths)}


def drill_family(catalog):
    return [p for p in catalog["positions"] if p["name"] == "Дрель ручная электрическая"]


def select_scope(catalog, scope="drills"):
    if scope == "drills":
        return drill_family(catalog)
    if scope == "all":
        return catalog["positions"]
    return [p for p in catalog["positions"] if scope in p["domains"]]


def family_facts(catalog, positions):
    keys = {p["key"] for p in positions}
    return [f for f in catalog["facts"] if any(s["position"] in keys for s in f["sources"])]


def fact_question(fact):
    return {
        "type": "choice",
        "instructions": f"Проверь факт о самом товаре: {fact['name']} = {fact['value']}. Выбери supported, contradicted, unknown или conflicting. Не переноси свойства упаковки на товар. Не додумывай отсутствующие данные.",
        "criteria": dict(STATUSES),
    }


def request_body(text, questions):
    return {"model": MODEL, "state": text, "questions": questions}


class SystemOneClient:
    def __init__(self, base_url="http://127.0.0.1:8769", timeout=180):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _json(self, path, body=None):
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        request = Request(self.base_url + path, data=payload, headers={"Content-Type": "application/json"})
        start = time.perf_counter()
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
        except HTTPError as error:
            raise RuntimeError(f"HTTP {error.code}: {error.read().decode(errors='replace')}") from error
        except (URLError, TimeoutError) as error:
            raise RuntimeError(f"API unavailable at {self.base_url}: {error}. Start the SSH tunnel; timed-out requests may still be running. No automatic retries.") from error
        return data, time.perf_counter() - start

    def health(self):
        info, _ = self._json("/health")
        if info.get("model") != MODEL:
            raise ValueError(f"Expected {MODEL}, health returned {info.get('model')}")
        return info

    def infer(self, body):
        response, elapsed = self._json("/v1/systemone", body)
        if response.get("model") != MODEL:
            raise ValueError("Response model differs from the experiment model")
        if set(response.get("answers", {})) != set(body["questions"]):
            raise ValueError("Response question IDs do not match request")
        for name, answer in response["answers"].items():
            question = body["questions"][name]
            if question["type"] == "noul":
                p = answer.get("noul")
                if not isinstance(p, (float, int)) or not math.isfinite(p) or not 0 <= p <= 1:
                    raise ValueError("Invalid noul probability")
                continue
            probabilities = answer.get("probabilities", {})
            if set(probabilities) != set(question["criteria"]):
                raise ValueError("Returned choices differ from supplied criteria")
            if any(not isinstance(p, (float, int)) or not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities.values()):
                raise ValueError("Invalid choice probabilities")
            if not math.isclose(sum(probabilities.values()), 1, abs_tol=1e-5):
                raise ValueError("Choice probabilities do not sum to one")
            if answer.get("choice") not in probabilities or probabilities[answer["choice"]] < max(probabilities.values()) - 1e-8:
                raise ValueError("Invalid selected choice")
        return {"request": body, "response": response, "elapsed_seconds": elapsed}


def smoke_jobs():
    """Hand-authored diagnostic labels, not a held-out KTRU accuracy benchmark."""
    cases = [
        ("battery", "Нужна аккумуляторная дрель.", "Тип питания", "От аккумулятора", "supported"),
        ("mains", "Дрель работает от сети 220 В.", "Тип питания", "От аккумулятора", "contradicted"),
        ("power_missing", "Нужна дрель с реверсом.", "Тип питания", "От аккумулятора", "unknown"),
        ("power_conflict", "Дрель только от аккумулятора. Исправления нет: она только от сети, аккумулятора нет.", "Тип питания", "От аккумулятора", "conflicting"),
        ("reverse_yes", "Дрель с реверсом.", "Наличие режима реверса", "Да", "supported"),
        ("reverse_no", "Дрель без реверса.", "Наличие режима реверса", "Да", "contradicted"),
        ("reverse_missing", "Дрель на 18 В.", "Наличие режима реверса", "Да", "unknown"),
        ("impact_no", "Дрель без ударного режима.", "Наличие режима ударного сверления", "Нет", "supported"),
        ("typo", "Акумуляторная дрелль с реверсом.", "Тип питания", "От аккумулятора", "supported"),
        ("armrests_no", "Нужен стул без подлокотников.", "Наличие подлокотников", "Да", "contradicted"),
        ("armrests_missing", "Нужен деревянный стул.", "Наличие подлокотников", "Да", "unknown"),
        ("package", "На упаковке написано: дрель с реверсом. Сам товар поставляется без реверса.", "Наличие режима реверса", "Да", "contradicted"),
    ]
    jobs = []
    for cid, text, name, value, expected in cases:
        fact = {"name": name, "value": value}
        jobs.append({"id": cid, "experiment": "smoke", "expected": {"fact": expected}, "baseline": {"fact": lexical_fact_status(text, fact)}, "body": request_body(text, {"fact": fact_question(fact)})})
    for cid, text, expected in (
        ("clothing_route", "Нужна зимняя мужская куртка.", "clothing"),
        ("furniture_route", "Нужен офисный стол.", "furniture"),
        ("tools_route", "Нужны пассатижи.", "tools"),
        ("outside_scope", "Нужен ноутбук с 16 ГБ памяти.", "other"),
    ):
        question = {"type": "choice", "instructions": "Определи категорию самого товара.", "criteria": {"clothing": "Одежда или обувь", "furniture": "Мебель", "tools": "Ручной или электрический инструмент", "other": "Другая категория или недостаточно данных"}}
        jobs.append({"id": cid, "experiment": "smoke", "expected": {"domain": expected}, "body": request_body(text, {"domain": question})})
    return jobs


def fact_jobs(catalog, text, chunk_size=4, scope="drills"):
    facts = sorted(family_facts(catalog, select_scope(catalog, scope)), key=lambda f: f["id"])
    jobs = []
    for offset in range(0, len(facts), chunk_size):
        chunk = facts[offset:offset + chunk_size]
        jobs.append({"id": f"facts_{offset}", "experiment": "facts", "facts": chunk,
                     "baseline": {f["id"]: lexical_fact_status(text, f) for f in chunk},
                     "body": request_body(text, {f["id"]: fact_question(f) for f in chunk})})
    return jobs


def slot_jobs(catalog, text, scope="drills"):
    """One categorical slot per catalog name, with explicit missing/conflict options."""
    grouped = defaultdict(list)
    for fact in family_facts(catalog, select_scope(catalog, scope)):
        grouped[(normalize(fact["name"]), fact["unit_code"])].append(fact)
    jobs = []
    for (name, unit), facts in sorted(grouped.items()):
        criteria = {f["id"]: f"Описание явно задает {f['name']} = {f['value']}." for f in facts}
        criteria.update(unknown="Значение не указано или не соответствует ни одному варианту.", conflicting="В описании одновременно несовместимые значения; нельзя выбрать одно.")
        if len(criteria) > 255:
            raise ValueError(f"Slot '{name}' exceeds 255 options; use the independent-facts suite")
        question = {"type": "choice", "instructions": f"Какое значение характеристики '{name}' указано для товара? Не додумывай значение. Для многозначных свойств используй отдельный эксперимент facts.", "criteria": criteria}
        jobs.append({"id": "slot_" + identity(name, unit), "experiment": "slots", "facts": facts, "body": request_body(text, {"slot": question})})
    return jobs


MEASURE = re.compile(r"(?<![\w.,])(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>квт|кв|вт|в|мм|см|м|а\s*[·*]?\s*ч)(?!\w)", re.I)
UNIT_TABLE = {"в": ("voltage", Decimal(1), "222"), "кв": ("voltage", Decimal(1000), "222"), "вт": ("power", Decimal(1), "212"), "квт": ("power", Decimal(1000), "212"), "мм": ("length", Decimal(1), "003"), "см": ("length", Decimal(10), "003"), "м": ("length", Decimal(1000), "003"), "ач": ("capacity", Decimal(1), "263")}
UNIT_SYMBOLS = {"222": "В", "212": "Вт", "003": "мм", "263": "А·ч"}


def measurements(text):
    result = []
    for i, match in enumerate(MEASURE.finditer(text)):
        unit = re.sub(r"[\s·*]", "", match["unit"].casefold())
        dimension, scale, okei = UNIT_TABLE[unit]
        value = Decimal(match["number"].replace(",", ".")) * scale
        result.append({"id": f"span_{i}", "raw": match.group(), "start": match.start(), "end": match.end(), "dimension": dimension, "value": str(value), "okei": okei})
    return result


def numeric_job(text):
    spans = measurements(text)
    criteria = {s["id"]: f"Этот фрагмент задает напряжение аккумулятора самого товара: {s['raw']} (позиции {s['start']}:{s['end']})." for s in spans if s["dimension"] == "voltage"}
    criteria.update(unknown="Напряжение аккумулятора не указано; напряжение сети или зарядника не подходит.", conflicting="Указаны несовместимые значения напряжения аккумулятора самого товара.")
    return {"id": "numeric", "experiment": "numeric", "spans": spans, "body": request_body(text, {"voltage": {"type": "choice", "instructions": "Выбери фрагмент с напряжением аккумулятора товара. Не присваивай ему напряжение зарядного устройства, сети или аксессуаров.", "criteria": criteria}})}


def numeric_jobs():
    cases = [
        ("voltage_exact", "Аккумуляторная дрель 18 В.", "span_0"),
        ("voltage_conversion", "Напряжение аккумулятора дрели 0,018 кВ.", "span_0"),
        ("charger", "Аккумуляторная дрель 18 В, зарядное устройство от сети 220 В.", "span_0"),
        ("charger_only", "Дрель с аккумулятором, зарядное устройство от сети 220 В.", "unknown"),
        ("voltage_conflict", "Напряжение аккумулятора дрели 18 В и одновременно 12 В; это один аккумулятор, сведения противоречат друг другу.", "conflicting"),
        ("voltage_missing", "Аккумуляторная дрель с реверсом.", "unknown"),
    ]
    jobs = []
    for cid, text, expected in cases:
        job = numeric_job(text)
        job.update(id=cid, expected={"voltage": expected})
        jobs.append(job)
    return jobs


def followup_jobs():
    """Paired numeric representations and labeled failures from saved runs."""
    jobs = []
    for original in numeric_jobs():
        for arm in ("raw", "normalized"):
            job = deepcopy(original)
            job.update(id=original["id"] + "_" + arm, experiment="numeric_" + arm,
                       pair_id=original["id"], arm=arm)
            if arm == "normalized":
                criteria = job["body"]["questions"]["voltage"]["criteria"]
                for span in job["spans"]:
                    if span["dimension"] == "voltage":
                        criteria[span["id"]] += f" Нормализованное значение: {span['value']} В; ОКЕИ {span['okei']}."
            jobs.append(job)
    cases = [
        ("tool_missing_impact", "tools", "Нужна дрель.", "Наличие режима ударного сверления", "Да", "unknown"),
        ("tool_impact_no", "tools", "Нужна аккумуляторная дрель с реверсом, без ударного режима.", "Наличие режима ударного сверления", "Нет", "supported"),
        ("tool_reverse_no", "tools", "Нужна аккумуляторная дрель с реверсом.", "Наличие режима реверса", "Нет", "contradicted"),
        ("tool_missing_battery_count", "tools", "Нужна аккумуляторная дрель.", "Количество аккумуляторов в комплекте, шт", "1", "unknown"),
        ("tool_missing_angle", "tools", "Нужна аккумуляторная дрель.", "Тип конструкции", "Угловая", "unknown"),
        ("tool_power_conflict", "tools", "В двух действующих разделах указаны взаимоисключающие требования к одной дрели: только от аккумулятора; только от сети. Оба требования остаются в силе.", "Тип питания", "От аккумулятора", "conflicting"),
        ("tool_power_correction", "tools", "Дрель от сети. Исправление: предыдущее требование отменено, нужна дрель только от аккумулятора.", "Тип питания", "От аккумулятора", "supported"),
        ("furniture_explicit", "furniture", "Нужен стул с подлокотниками.", "Наличие подлокотников", "Да", "supported"),
        ("furniture_missing", "furniture", "Нужен деревянный стул.", "Наличие подлокотников", "Да", "unknown"),
        ("furniture_negation", "furniture", "Нужен стул без подлокотников.", "Наличие подлокотников", "Да", "contradicted"),
        ("furniture_package", "furniture", "На коробке указан стул с подлокотниками. Сам стул поставляется без подлокотников.", "Наличие подлокотников", "Да", "contradicted"),
        ("furniture_conflict", "furniture", "Для одного стула действуют два несовместимых требования: наличие подлокотников — да; наличие подлокотников — нет. Ни одно не отменено.", "Наличие подлокотников", "Да", "conflicting"),
        ("clothing_explicit", "clothing", "Нужна куртка из хлопка.", "Материал", "Хлопок", "supported"),
        ("clothing_missing", "clothing", "Нужна синяя куртка.", "Материал", "Хлопок", "unknown"),
        ("clothing_negation", "clothing", "Куртка из полиэстера, хлопка в составе нет.", "Материал", "Хлопок", "contradicted"),
        ("clothing_package", "clothing", "Куртка из полиэстера без хлопка. Упаковочный мешок изготовлен из хлопка.", "Материал", "Хлопок", "contradicted"),
        ("clothing_correction", "clothing", "Куртка из хлопка. Исправление состава: предыдущее указание отменено, материал — полиэстер, хлопка нет.", "Материал", "Хлопок", "contradicted"),
    ]
    for cid, domain, text, name, value, expected in cases:
        fact = {"name": name, "value": value}
        jobs.append({"id": cid, "experiment": "fact_followup", "domain": domain,
                     "facts": [fact], "expected": {"fact": expected},
                     "baseline": {"fact": lexical_fact_status(text, fact)},
                     "body": request_body(text, {"fact": fact_question(fact)})})
    return jobs


def supported_metrics(records, threshold=0.8):
    """Successful fact checks only; API failures have a separate count."""
    counts = Counter(evaluated=0, errors=0, true_supported=0, predicted_supported=0,
                     correct_supported=0, unsupported_additions=0,
                     accepted_supported=0, accepted_correct_supported=0,
                     accepted_unsupported_additions=0)
    for record in records:
        if record["experiment"] != "fact_followup":
            continue
        if "error" in record:
            counts["errors"] += 1
            continue
        for name, expected in record["expected"].items():
            answer = record["response"]["answers"][name]
            positive = answer["choice"] == "supported"
            accepted = positive and answer["probabilities"]["supported"] >= threshold
            counts["evaluated"] += 1
            counts["true_supported"] += expected == "supported"
            counts["predicted_supported"] += positive
            counts["correct_supported"] += positive and expected == "supported"
            counts["unsupported_additions"] += positive and expected != "supported"
            counts["accepted_supported"] += accepted
            counts["accepted_correct_supported"] += accepted and expected == "supported"
            counts["accepted_unsupported_additions"] += accepted and expected != "supported"
    def ratio(numerator, denominator):
        return counts[numerator] / counts[denominator] if counts[denominator] else None
    return dict(counts, supported_precision=ratio("correct_supported", "predicted_supported"),
                supported_recall=ratio("correct_supported", "true_supported"),
                accepted_precision=ratio("accepted_correct_supported", "accepted_supported"),
                threshold_uncalibrated=threshold)


def followup_report(records, jobs, threshold=0.8):
    by_id = {r["id"]: r for r in records}
    report = {"supported_facts": supported_metrics(records, threshold), "numeric_pairs": [],
              "fact_domains": {}, "planned_requests": len(jobs),
              "completed_requests": len(records),
              "complete": len(records) == len(jobs) and not any("error" in r for r in records),
              "note": "Development fixtures; supported precision/recall exclude API errors. Status accuracy counts recorded errors; unexecuted jobs are not scored."}
    for job in jobs:
        if job.get("arm") != "raw":
            continue
        pair = {"case": job["pair_id"], "expected": job["expected"]["voltage"]}
        for arm in ("raw", "normalized"):
            record = by_id.get(job["pair_id"] + "_" + arm)
            pair[arm] = (record["response"]["answers"]["voltage"] if record and "response" in record
                         else {"error": record.get("error", "not executed") if record else "not executed"})
        report["numeric_pairs"].append(pair)
    for domain in sorted({j["domain"] for j in jobs if "domain" in j}):
        group = [r for r in records if r.get("domain") == domain]
        report["fact_domains"][domain] = {"status": summarize(group)["experiments"].get("fact_followup", {}),
                                          "supported_facts": supported_metrics(group, threshold)}
    return report


def progressive_jobs(catalog, chunk_size=4):
    descriptions = ["Нужна дрель.", "Нужна аккумуляторная дрель.", "Нужна аккумуляторная дрель с реверсом.", "Нужна аккумуляторная дрель с реверсом, без ударного режима."]
    jobs = []
    for step, text in enumerate(descriptions):
        for job in fact_jobs(catalog, text, chunk_size):
            job.update(id=f"step_{step}_{job['id']}", experiment="progressive", step=step)
            jobs.append(job)
    return jobs


def order_jobs():
    job = smoke_jobs()[0]
    question = job["body"]["questions"]["fact"]
    jobs = []
    for index, labels in enumerate((list(STATUSES), list(reversed(STATUSES)), list(STATUSES))):
        q = dict(question, criteria={label: STATUSES[label] for label in labels})
        jobs.append({"id": f"order_{index}", "experiment": "order", "expected": {"fact": "supported"}, "body": request_body(job["body"]["state"], {"fact": q})})
    return jobs


def lexical_fact_status(text, fact):
    """Conservative exact-value baseline; intentionally does not infer synonyms."""
    value = normalize(fact["value"])
    if value in {"да", "нет"}:
        return "unknown"
    pattern = r"(?<!\w)" + re.escape(value) + r"(?!\w)"
    return "supported" if re.search(pattern, normalize(text)) else "unknown"


def narrow_candidates(positions, facts, records, threshold=0.8):
    """Exploratory qualitative filtering within a fixed drill family only.

    Accept only supported facts above an uncalibrated configurable threshold.
    Missing properties remain extras. No final code or required-field completion
    is claimed. Contradicted hypotheses alone do not eliminate a position whose
    schema allows several values (catalog options are permissions, not facts).
    """
    evidence = {}
    for record in records:
        for fid, answer in record.get("response", {}).get("answers", {}).items():
            if fid in {f["id"] for f in facts}:
                evidence[fid] = answer
    supported = [f for f in facts if evidence.get(f["id"], {}).get("choice") == "supported" and evidence[f["id"]]["probabilities"]["supported"] >= threshold]
    # Inconsistent positive values are not trustworthy exclusion evidence.
    grouped = defaultdict(list)
    for fact in supported:
        grouped[(normalize(fact["name"]), fact["unit_code"])].append(fact)
    ambiguous = {key for key, vals in grouped.items() if len(vals) > 1}
    result = []
    for position in positions:
        matched, conflicts, extras, uncertain = [], [], [], []
        for fact in supported:
            key = (normalize(fact["name"]), fact["unit_code"])
            chars = [c for c in position["characteristics"] if normalize(c["name"]) == key[0]]
            if not chars:
                extras.append(fact["id"])
                continue
            if key in ambiguous and any(c["kind"] != "3" for c in chars):
                uncertain.append(fact["id"])
                continue
            allowed = {normalize(v["text"]) for c in chars for v in c["values"] if v["text"] and v["unit_code"] == key[1]}
            if not allowed:
                uncertain.append(fact["id"])
            elif normalize(fact["value"]) in allowed:
                matched.append(fact["id"])
            else:
                conflicts.append(fact["id"])
        result.append({"code": position["code"], "version": position["version"], "name": position["name"], "compatible": not conflicts, "matches": matched, "conflicts": conflicts, "extras": extras, "uncertain": uncertain})
    return result


def summarize(records):
    totals = defaultdict(lambda: Counter(correct=0, labeled=0, requests=0, errors=0))
    confusion = Counter()
    baseline = Counter(correct=0, labeled=0)
    latencies = defaultdict(list)
    for record in records:
        group = totals[record["experiment"]]
        group["requests"] += 1
        for name, predicted in record.get("baseline", {}).items():
            if name in record.get("expected", {}):
                baseline["labeled"] += 1
                baseline["correct"] += predicted == record["expected"][name]
        if "error" in record:
            group["errors"] += 1
            group["labeled"] += len(record.get("expected", {}))
            continue
        latencies[record["experiment"]].append(record["elapsed_seconds"])
        for name, expected in record.get("expected", {}).items():
            predicted = record["response"]["answers"][name]["choice"]
            group["labeled"] += 1
            group["correct"] += predicted == expected
            confusion[(expected, predicted)] += 1
    summary = {name: dict(counts, accuracy=counts["correct"] / counts["labeled"] if counts["labeled"] else None) for name, counts in totals.items()}
    for name, durations in latencies.items():
        summary[name]["latency_seconds"] = {"median": statistics.median(durations), "p95": sorted(durations)[math.ceil(len(durations) * .95) - 1], "samples": len(durations)}
    return {"experiments": summary, "exact_value_baseline": dict(baseline, accuracy=baseline["correct"] / baseline["labeled"] if baseline["labeled"] else None), "confusion": [{"expected": a, "predicted": b, "count": n} for (a, b), n in sorted(confusion.items())]}


def run_jobs(client, jobs, output_dir, catalog=None, threshold=0.8, scope="drills"):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        health = client.health()
    except (RuntimeError, ValueError) as error:
        (output_dir / "startup_error.json").write_text(json.dumps({"error": str(error), "base_url": client.base_url}, indent=2) + "\n")
        raise
    (output_dir / "health.json").write_text(json.dumps(health, ensure_ascii=False, indent=2) + "\n")
    manifest = {"model": MODEL, "base_url": client.base_url, "timeout": client.timeout, "scope": scope, "threshold_uncalibrated": threshold, "planned_requests": len(jobs), "diagnostic_not_held_out": True}
    if catalog:
        manifest["catalog_sha256"] = hashlib.sha256(json.dumps(catalog, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    records = []
    with (
        (output_dir / "requests.jsonl").open("w", encoding="utf-8") as log,
        (output_dir / "model_requests.jsonl").open("w", encoding="utf-8") as request_log,
    ):
        for index, job in enumerate(jobs):
            print(f"{index + 1}/{len(jobs)} {job['experiment']} {job['id']}", flush=True)
            record = {k: v for k, v in job.items() if k != "body"}
            # Save before dispatch so in-flight and interrupted calls remain inspectable.
            outgoing = {
                "logged_at": datetime.now(timezone.utc).isoformat(),
                "id": job["id"], "experiment": job["experiment"],
                "method": "POST", "url": client.base_url.rstrip("/") + "/v1/systemone",
                "request": job["body"],
            }
            serialized = json.dumps(outgoing, ensure_ascii=False)
            request_log.write(serialized + "\n")
            request_log.flush()
            print("Model request: " + serialized, flush=True)
            try:
                record.update(client.infer(job["body"]))
                if "spans" in job:
                    choice = record["response"]["answers"][job.get("binding_question", "voltage")]["choice"]
                    record["bound_measurement"] = next((s for s in job["spans"] if s["id"] == choice), None)
            except (RuntimeError, ValueError) as error:
                record.update(request=job["body"], error=str(error))
            records.append(record)
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
            log.flush()
            if "error" in record:
                break  # A timed-out shared-GPU call might still be running.
    summary = summarize(records)
    summary.update(planned_requests=len(jobs), completed_requests=len(records), stopped_early=len(records) < len(jobs))
    order = [r for r in records if r["experiment"] == "order" and "response" in r]
    if len(order) >= 2:
        distributions = [r["response"]["answers"]["fact"]["probabilities"] for r in order]
        summary["order_sensitivity"] = {
            "choices": [r["response"]["answers"]["fact"]["choice"] for r in order],
            "max_probability_delta_from_first": max(abs(p[key] - distributions[0][key]) for p in distributions[1:] for key in distributions[0]),
            "note": "Includes reversed option order and an identical repeat; diagnostic only.",
        }
    if catalog:
        summary["narrowing"] = {}
        groups = defaultdict(list)
        for record in records:
            if record["experiment"] in {"facts", "progressive"}:
                groups[(record["experiment"], record.get("step", 0))].append(record)
        for (experiment, step), group in groups.items():
            positions = select_scope(catalog, "drills" if experiment == "progressive" else scope)
            facts = family_facts(catalog, positions)
            answered = {fid for record in group for fid in record.get("response", {}).get("answers", {})}
            summary["narrowing"][f"{experiment}_{step}"] = {
                "complete_fact_scan": {f["id"] for f in facts} <= answered,
                "candidates": narrow_candidates(positions, facts, group, threshold),
            }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    if any(j["experiment"] == "fact_followup" for j in jobs):
        (output_dir / "followup_report.json").write_text(json.dumps(followup_report(records, jobs, threshold), ensure_ascii=False, indent=2) + "\n")
    return records, summary


def build_jobs(catalog, suite="smoke", text="Нужна аккумуляторная дрель 18 В с реверсом, без ударного режима.", chunk_size=4, scope="drills"):
    builders = {
        "smoke": smoke_jobs,
        "numeric": numeric_jobs,
        "followup": followup_jobs,
        "order": order_jobs,
        "facts": lambda: fact_jobs(catalog, text, chunk_size, scope),
        "slots": lambda: slot_jobs(catalog, text, scope),
        "progressive": lambda: progressive_jobs(catalog, chunk_size),
    }
    return builders[suite]()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("smoke", "numeric", "followup", "order", "facts", "slots", "progressive"), default="smoke")
    parser.add_argument("--base-url", default="http://127.0.0.1:8769")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--text", default="Нужна аккумуляторная дрель 18 В с реверсом, без ударного режима.")
    parser.add_argument("--chunk-size", type=int, default=4)
    parser.add_argument("--scope", choices=("drills", "clothing", "furniture", "tools", "all"), default="drills", help="catalog scope for facts/slots; progressive always uses the drill family")
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--dry-run", action="store_true", help="prepare requests without any network calls")
    parser.add_argument("--catalog-cache", type=Path, default=ROOT / "experiments/results/nimble_catalog.json")
    parser.add_argument("--rebuild-catalog", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.chunk_size < 1 or not 0 <= args.threshold <= 1 or args.timeout <= 0:
        parser.error("chunk-size and timeout must be positive; threshold must be in [0,1]")
    catalog = None
    if args.suite in {"facts", "slots", "progressive"}:
        if args.catalog_cache.exists() and not args.rebuild_catalog:
            catalog = json.loads(args.catalog_cache.read_text())
        else:
            catalog = load_catalog()
            args.catalog_cache.parent.mkdir(parents=True, exist_ok=True)
            args.catalog_cache.write_text(json.dumps(catalog, ensure_ascii=False) + "\n")
        if len(drill_family(catalog)) < 2:
            raise ValueError("Expected at least two distinct drill positions in the source snapshot")
    jobs = build_jobs(catalog, args.suite, args.text, args.chunk_size, args.scope)
    if args.dry_run:
        print(json.dumps({"suite": args.suite, "requests": len(jobs), "questions": sum(len(j['body']['questions']) for j in jobs), "first_request": jobs[0]["body"], "catalog_positions": len(catalog["positions"]) if catalog else None}, ensure_ascii=False, indent=2))
        return 0
    output = args.output or ROOT / "experiments/results" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + args.suite)
    _, summary = run_jobs(SystemOneClient(args.base_url, args.timeout), jobs, output, catalog, args.threshold, args.scope)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Results:", output)
    return int(any(v["errors"] for v in summary["experiments"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
