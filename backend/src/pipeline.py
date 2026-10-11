from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Literal

from experiments import classifier_experiments as ce

from backend.src.models import KtruCharacteristic, KtruPosition, KtruValue

if TYPE_CHECKING:
    from backend.src.retrieval import Retrieval

CheckStatus = Literal["matched", "conflict", "unknown"]
AnalysisStatus = Literal["retrieval_miss", "incomplete_inference", "no_compatible_shortlist_candidate",
                         "needs_clarification", "ready_for_review"]


def value_key(name: str, value: str) -> str:
    return ce.normalize(ce.canonical_value(name, value))


def position_reference(position: KtruPosition) -> dict:
    return {"import_sha256": position.import_sha256, "code": position.code,
            "version": str(position.version), "name": position.name,
            "source_file_id": position.source_file_id, "source_line": position.source_line,
            "xml_id": position.xml_id, "version_code": position.version_code,
            "external_code": position.external_code, "status": position.status,
            "updated": position.updated.isoformat() if position.updated is not None else None,
            "applies_from": position.applies_from.isoformat() if position.applies_from is not None else None,
            "applies_to": position.applies_to.isoformat() if position.applies_to is not None else None,
            "no_new_features": position.no_new_features,
            "no_new_features_reason": position.no_new_features_reason,
            "units": position.units, "rubrics": position.rubrics,
            "rubric_codes": position.rubric_codes}


def value_snapshot(value: KtruValue) -> dict:
    return {"id": value.id, "code": value.code, "ordinal": value.ordinal,
            "text": value.text, "okei": value.okei, "issue": value.issue,
            "value_format": value.value_format,
            "spans": [{"lower": str(span.lower) if span.lower is not None else None,
                       "upper": str(span.upper) if span.upper is not None else None,
                       "bounds": span.bounds, "empty": span.empty}
                      for span in value.spans or []]}


@dataclass
class Source:
    position: KtruPosition
    characteristic: KtruCharacteristic
    value: KtruValue

    def snapshot(self) -> dict:
        return {**position_reference(self.position),
                "characteristic_code": self.characteristic.code,
                "characteristic_name": self.characteristic.name,
                "value_id": self.value.id, "value": value_snapshot(self.value)}


@dataclass
class Hypothesis:
    id: str
    name: str
    value: str
    unit: str | None
    sources: list[Source] = field(default_factory=list)

    def snapshot(self) -> dict:
        return {"id": self.id, "name": self.name, "value": self.value, "unit": self.unit,
                "sources": [source.snapshot() for source in self.sources]}


@dataclass
class Binding:
    position: KtruPosition
    characteristic: KtruCharacteristic
    unit: str | None
    hypotheses: list[Hypothesis] = field(default_factory=list)
    question_id: str | None = None
    spans: list[dict] = field(default_factory=list)

    def snapshot(self) -> dict:
        char = self.characteristic
        return {**position_reference(self.position), "characteristic_code": char.code,
                "name": char.name, "is_numeric": char.is_numeric, "choice": char.choice,
                "required": char.required, "actual": char.actual, "choice_type": char.choice_type,
                "unit": self.unit, "hypothesis_ids": [h.id for h in self.hypotheses],
                "question_id": self.question_id, "spans": self.spans,
                "values": [value_snapshot(value) for value in char.values]}


@dataclass
class Job:
    id: str
    experiment: str
    body: dict
    hypotheses: list[Hypothesis] = field(default_factory=list)
    bindings: list[Binding] = field(default_factory=list)
    positions: list[KtruPosition] = field(default_factory=list)

    def snapshot(self) -> dict:
        return {"id": self.id, "experiment": self.experiment, "body": self.body,
                "facts": [h.snapshot() for h in self.hypotheses],
                "bindings": [binding.snapshot() for binding in self.bindings],
                "positions": [position_reference(p) for p in self.positions]}


@dataclass
class Plan:
    text: str
    retrieval: Retrieval
    hypotheses: list[Hypothesis]
    bindings: list[Binding]
    spans: list[dict]
    jobs: list[Job]

    @property
    def question_count(self) -> int:
        return sum(len(job.body["questions"]) for job in self.jobs)

    def snapshot(self) -> dict:
        return {"text": self.text, "import_sha256": self.retrieval.import_sha256,
                "retrieval": self.retrieval.metadata(), "question_count": self.question_count,
                "positions": [position_reference(p) for p in self.retrieval.positions],
                "jobs": [job.snapshot() for job in self.jobs]}


def scalar_span(span: dict, text: str) -> bool:
    """A range endpoint, bound or signed number is not a point observation."""
    left, right = text[:span["start"]], text[span["end"]:]
    clause = re.split(r"[;|\n]", left)[-1] + span["raw"] + re.split(r"[;|\n]", right)[0]
    return not (re.search(r"[-−<>≤≥≈±]\s*$", left)
                or re.match(r"\s*[-–—±]\s*\d", right)
                or re.search(r"\d\s*[-–—]\s*\d|не\s+(?:менее|более)|(?:от|до)\s+\d|[<>≤≥≈±]",
                             clause, re.IGNORECASE))


def prepare(retrieval: Retrieval, text: str, chunk_size: int = 4,
            max_questions: int = 128) -> Plan:
    if not 1 <= chunk_size <= 8:
        raise ValueError("chunk_size must be between 1 and 8")
    hypotheses: dict[tuple, Hypothesis] = {}
    scoped: dict[tuple, list[Hypothesis]] = {}
    jobs: list[Job] = []
    products: dict[str, list[KtruPosition]] = {}
    for position in retrieval.positions:
        if position.import_sha256 != retrieval.import_sha256:
            raise ValueError("Retrieved positions must belong to the selected import")
        products.setdefault(ce.normalize(position.name), []).append(position)
        for char in position.characteristics:
            if not char.actual or char.is_numeric:
                continue
            for value in char.values:
                if not value.text or value.issue:
                    continue
                key = (ce.normalize(char.name), value_key(char.name, value.text), value.okei)
                hypothesis = hypotheses.setdefault(key, Hypothesis(
                    "fact_" + ce.identity(*key), char.name,
                    ce.canonical_value(char.name, value.text), value.okei))
                hypothesis.sources.append(Source(position, char, value))
                # A name is an extraction prompt, not a characteristic identity.
                scope = (char.code, ce.normalize(char.name), value.okei)
                group = scoped.setdefault(scope, [])
                if hypothesis not in group:
                    group.append(hypothesis)
    for name, positions in sorted(products.items()):
        qid = "product_" + ce.identity(name)
        question = ce.fact_question({"name": "Вид самого товара", "value": positions[0].name})
        jobs.append(Job(qid, "pipeline_product", ce.request_body(text, {qid: question}),
                        positions=positions))
    facts = sorted(hypotheses.values(), key=lambda h: h.id)
    for offset in range(0, len(facts), chunk_size):
        chunk = facts[offset:offset + chunk_size]
        questions = {h.id: ce.fact_question({"name": h.name, "value": h.value}) for h in chunk}
        jobs.append(Job(f"categorical_{offset}", "pipeline_facts", ce.request_body(text, questions), chunk))
    spans = ce.measurements(text)
    bindings: list[Binding] = []
    numeric_groups: dict[tuple, list[Binding]] = {}
    for position in retrieval.positions:
        for char in position.characteristics:
            if not char.actual:
                continue
            units = dict.fromkeys(value.okei for value in char.values) or {None: None}
            for unit in units:
                binding = Binding(position, char, unit)
                bindings.append(binding)
                scope = (char.code, ce.normalize(char.name), unit)
                if not char.is_numeric:
                    binding.hypotheses = scoped.get(scope, [])
                    continue
                binding.spans = [span for span in spans if span["okei"] == unit and scalar_span(span, text)]
                if binding.spans:
                    binding.question_id = "measurement_" + ce.identity(*scope)
                    numeric_groups.setdefault(scope, []).append(binding)
    for scope, group in sorted(numeric_groups.items(), key=lambda item: repr(item[0])):
        binding = group[0]
        if len(binding.spans) > 253:
            raise ValueError("Too many numeric spans for a choice question; shorten the input")
        criteria = {span["id"]: f"Фрагмент {span['raw']} (позиции {span['start']}:{span['end']}) явно задает '{binding.characteristic.name}' самого товара; нормализованное значение {span['value']}, ОКЕИ {span['okei']}."
                    for span in binding.spans}
        criteria.update(unknown="Свойство не указано. Числа упаковки, аксессуаров и других объектов не подходят.",
                        conflicting="Для одного свойства товара одновременно указаны несовместимые значения, ни одно не отменено.")
        question = {"type": "choice", "instructions": f"Выбери точное числовое значение свойства '{binding.characteristic.name}' самого товара. Учитывай контекст и исправления. Не подставляй число только из-за совпадения единицы измерения.",
                    "criteria": criteria}
        jobs.append(Job("binding_" + ce.identity(*scope), "pipeline_numeric",
                        ce.request_body(text, {binding.question_id: question}), bindings=group))
    plan = Plan(text, retrieval, facts, bindings, spans, jobs)
    if plan.question_count > max_questions:
        raise ValueError(f"Shortlist requires {plan.question_count} questions, above BACKEND_MAX_QUESTIONS={max_questions}; reduce top_k or inspect a narrower scope")
    return plan


def numeric_rule(point: Decimal | str, value: KtruValue) -> bool | None:
    """Product point membership in one source value group (union of its spans)."""
    if value.issue or not value.spans:
        return None
    try:
        point = Decimal(point)
        if not point.is_finite():
            return None
        for span in value.spans:
            if span.empty:
                continue
            lower = Decimal(span.lower) if span.lower is not None else None
            upper = Decimal(span.upper) if span.upper is not None else None
            if ((lower is None or point > lower or (span.lower_inc and point == lower))
                    and (upper is None or point < upper or (span.upper_inc and point == upper))):
                return True
        return False
    except (InvalidOperation, TypeError, ValueError):
        return None


def product_numeric_check(char: KtruCharacteristic, point: Decimal | str,
                          unit: str | None) -> CheckStatus:
    alternatives = [numeric_rule(point, value) for value in char.values if value.okei == unit]
    return ("matched" if True in alternatives else
            "unknown" if not alternatives or None in alternatives else "conflict")


def validate_categorical_selection(char: KtruCharacteristic,
                                   value_ids: Sequence[int]) -> CheckStatus:
    """Strict procurement selection by source ID, not a product observation."""
    if char.is_numeric:
        return "conflict"
    allowed = {value.id: value for value in char.values}
    selected = set(value_ids)
    if len(selected) != len(value_ids) or not selected <= allowed.keys():
        return "conflict"
    if not selected:
        return "unknown" if char.required or char.choice == "fixed" else "matched"
    if char.choice == "fixed" and selected != allowed.keys():
        return "conflict"
    if char.choice == "one_of" and len(selected) != 1:
        return "conflict"
    if char.choice not in {"fixed", "one_of", "many_of"}:
        return "unknown"
    return "unknown" if any(allowed[id].issue or not allowed[id].text for id in selected) else "matched"


def validate_numeric_selection(char: KtruCharacteristic,
                               selections: Sequence[tuple[int, Decimal]]) -> CheckStatus:
    """Procurement chooses source groups first, then a point within each group."""
    if not char.is_numeric:
        return "conflict"
    allowed = {value.id: value for value in char.values}
    ids = [id for id, _ in selections]
    if len(set(ids)) != len(ids) or not set(ids) <= allowed.keys():
        return "conflict"
    if not ids:
        return "unknown" if char.required or char.choice == "fixed" else "matched"
    if char.choice == "fixed" and set(ids) != allowed.keys():
        return "conflict"
    if char.choice == "one_of" and len(ids) != 1:
        return "conflict"
    if char.choice not in {"fixed", "one_of", "many_of"}:
        return "unknown"
    outcomes = [numeric_rule(point, allowed[id]) for id, point in selections]
    return "conflict" if False in outcomes else "unknown" if None in outcomes else "matched"


def extra_action(position: KtruPosition, name: str) -> str:
    if any(char.actual and ce.normalize(char.name) == ce.normalize(name) for char in position.characteristics):
        return "map_and_validate"
    return ("do_not_add" if position.no_new_features is True else
            "review_before_add" if position.no_new_features is False else
            "additional_field_policy_unknown")


def accepted(answer: dict | None, choice: str, threshold: float) -> bool:
    return bool(answer and answer["choice"] == choice
                and answer["probabilities"].get(choice, 0) >= threshold)


@dataclass
class Finding:
    binding: Binding
    status: CheckStatus
    reason: str
    hypotheses: list[Hypothesis] = field(default_factory=list)
    span: dict | None = None

    def snapshot(self) -> dict:
        return {"binding": self.binding.snapshot(), "status": self.status,
                "reason": self.reason, "hypothesis_ids": [h.id for h in self.hypotheses],
                "span": self.span}


@dataclass
class CandidateAssessment:
    position: KtruPosition
    status: Literal["supported", "uncertain", "rejected"]
    product_answer: dict | None
    findings: list[Finding]
    missing_required: list[KtruCharacteristic]
    unmatched: list[Hypothesis]
    extras: list[dict]
    reasons: list[str]

    def snapshot(self) -> dict:
        return {**position_reference(self.position), "assessment": self.status,
                "product_relevance": self.product_answer, "reasons": self.reasons,
                "checks": [finding.snapshot() for finding in self.findings],
                "missing_required": [{"code": char.code, "name": char.name} for char in self.missing_required],
                "unmatched_hypothesis_ids": [h.id for h in self.unmatched],
                "extra_characteristics": self.extras, "lifecycle_review_required": True}


@dataclass
class Report:
    plan: Plan
    status: AnalysisStatus
    complete_inference: bool
    recommended: KtruPosition | None
    candidates: list[CandidateAssessment]
    properties: list[tuple[str, str]]
    clarifying_question: str | None
    warnings: list[str]
    answers: dict[str, dict]
    threshold: float

    def snapshot(self) -> dict:
        return {"status": self.status, "final_code": None,
                "provisional_candidate": self.recommended.code if self.recommended is not None else None,
                "input": self.plan.text, "import_sha256": self.plan.retrieval.import_sha256,
                "retrieval": self.plan.retrieval.metadata(), "complete_inference": self.complete_inference,
                "threshold_uncalibrated": self.threshold, "answers": self.answers,
                "categorical_facts": [dict(h.snapshot(), answer=self.answers.get(h.id)) for h in self.plan.hypotheses],
                "candidates": [candidate.snapshot() for candidate in self.candidates],
                "clarifying_question": self.clarifying_question, "warnings": self.warnings}


def categorical_check(binding: Binding, answers: dict[str, dict], threshold: float) -> Finding:
    char = binding.characteristic
    positive = [h for h in binding.hypotheses if accepted(answers.get(h.id), "supported", threshold)]
    conflicting = [h for h in binding.hypotheses if accepted(answers.get(h.id), "conflicting", threshold)]
    values = [v for v in char.values if v.okei == binding.unit]
    allowed = {value_key(char.name, v.text) for v in values if v.text and not v.issue}
    unknown_rules = not values or any(v.issue or not v.text for v in values)
    if conflicting or (char.choice == "one_of" and len(positive) > 1):
        return Finding(binding, "unknown", "Неоднозначные значения характеристики.", positive + conflicting)
    if positive:
        unlisted = [h for h in positive if value_key(char.name, h.value) not in allowed]
        if unlisted:
            return Finding(binding, "unknown" if unknown_rules else "conflict",
                           "Правило каталога требует проверки." if unknown_rules else "Значение не допускается этой характеристикой.", unlisted)
        return Finding(binding, "matched", "Значение подтверждено описанием.", positive)
    if char.choice == "fixed" and allowed and not unknown_rules:
        own = [h for h in binding.hypotheses if value_key(char.name, h.value) in allowed]
        if own and any(accepted(answers.get(h.id), "contradicted", threshold) for h in own):
            return Finding(binding, "conflict", "Описание отрицает фиксированное значение.", own)
    return Finding(binding, "unknown", "Правило каталога требует проверки." if unknown_rules else "Значение не указано.")


def analyze(plan: Plan, records: list[dict], threshold: float = .8,
            confirmed_extras: Sequence[dict] = ()) -> Report:
    answers: dict[str, dict] = {}
    complete = True
    by_job = {record["id"]: record for record in records if "response" in record}
    for job in plan.jobs:
        incoming = by_job.get(job.id, {}).get("response", {}).get("answers", {})
        complete &= set(incoming) == set(job.body["questions"])
        answers.update({qid: answer for qid, answer in incoming.items() if qid in job.body["questions"]})
    candidates: list[CandidateAssessment] = []
    properties: set[tuple[str, str]] = set()
    warnings = ["Результат не является окончательным кодом или подтверждением соответствия; применимость и жизненный цикл позиции требуют проверки."]
    if plan.retrieval.truncated:
        warnings.append("Часть найденных позиций не вошла в список кандидатов.")
    if any(binding.characteristic.is_numeric for binding in plan.bindings):
        warnings.append("Числовое извлечение ограничено точечными значениями и поддерживаемыми единицами; совпадение единицы не подтверждает связь с характеристикой.")
    used_spans: set[str] = set()
    unresolved: set[str] = set()
    for position in plan.retrieval.positions:
        findings: list[Finding] = []
        missing: list[KtruCharacteristic] = []
        scoped_ids: set[str] = set()
        reasons: list[str] = []
        product = answers.get("product_" + ce.identity(ce.normalize(position.name)))
        object_supported = accepted(product, "supported", threshold)
        rejected = accepted(product, "contradicted", threshold)
        uncertain = not object_supported
        if not object_supported:
            reasons.append("Указанный вид товара не соответствует описанию." if rejected else "Вид товара не подтверждён описанием.")
        for char in position.characteristics:
            if not char.actual:
                continue
            covered = False
            char_bindings = [b for b in plan.bindings if b.position is position and b.characteristic is char]
            positive_ids = {h.id for b in char_bindings for h in b.hypotheses
                            if accepted(answers.get(h.id), "supported", threshold)}
            ambiguous = not char.is_numeric and char.choice == "one_of" and len(positive_ids) > 1
            for binding in char_bindings:
                if not char.is_numeric:
                    scoped_ids.update(h.id for h in binding.hypotheses)
                    finding = categorical_check(binding, answers, threshold)
                    if ambiguous and finding.hypotheses:
                        finding = Finding(binding, "unknown", "Неоднозначные значения характеристики.", finding.hypotheses)
                else:
                    answer = answers.get(binding.question_id) if binding.question_id is not None else None
                    span = next((s for s in binding.spans if accepted(answer, s["id"], threshold)), None)
                    if span:
                        used_spans.add(span["id"])
                        numeric_status = product_numeric_check(char, span["value"], binding.unit)
                        finding = Finding(binding, numeric_status,
                                          "Вне допустимых значений." if numeric_status == "conflict" else
                                          "Правило каталога требует проверки." if numeric_status == "unknown" else
                                          "Числовое значение допустимо.", span=span)
                        properties.add((char.name, f"{format(Decimal(span['value']).normalize(), 'f')} {ce.UNIT_SYMBOLS.get(span['okei'], span['okei'])}"))
                    else:
                        conflict = accepted(answer, "conflicting", threshold)
                        if conflict:
                            unresolved.add(char.name)
                        finding = Finding(binding, "unknown", "Противоречивые числовые значения." if conflict else "Значение не указано.")
                findings.append(finding)
                covered |= finding.status == "matched"
                rejected |= finding.status == "conflict"
                # Missing information is not evidence against a compatible product.
                rule_issue = any(v.issue for v in char.values) or not char.values
                uncertain |= (finding.status == "unknown" and
                              (bool(finding.hypotheses) or finding.span is not None or rule_issue
                               or (binding.question_id is not None and accepted(answers.get(binding.question_id), "conflicting", threshold))))
                if finding.status == "conflict" or (finding.status == "unknown" and (finding.hypotheses or finding.span or rule_issue)):
                    reasons.append(f"{char.name}: {finding.reason}")
                if finding.status == "matched" and not char.is_numeric:
                    properties.update((h.name, h.value) for h in finding.hypotheses)
            if char.required and not covered:
                missing.append(char)
        unmatched = [h for h in plan.hypotheses if h.id not in scoped_ids and accepted(answers.get(h.id), "supported", threshold)]
        extras = [dict(extra, action=extra_action(position, extra["name"])) for extra in confirmed_extras]
        candidate_status = "rejected" if rejected else "uncertain" if uncertain else "supported"
        if candidate_status == "supported":
            reasons.append("Вид товара подтверждён, выполненные проверки характеристик пройдены.")
        candidates.append(CandidateAssessment(position, candidate_status, product, findings, missing, unmatched, extras, reasons))
    # Independent many_of values survive even if another candidate's one_of is ambiguous.
    for hypothesis in plan.hypotheses:
        if accepted(answers.get(hypothesis.id), "conflicting", threshold):
            warnings.append(f"{hypothesis.name}: «{hypothesis.value}» — модель обнаружила противоречие в описании.")
            unresolved.add(hypothesis.name)
        if accepted(answers.get(hypothesis.id), "supported", threshold) and not any(
                finding.status == "unknown" and hypothesis in finding.hypotheses
                for candidate in candidates for finding in candidate.findings):
            properties.add((hypothesis.name, hypothesis.value))
    if unresolved:
        warnings.append("Противоречивые значения требуют уточнения: " + ", ".join(sorted(unresolved)) + ".")
    unbound = [span["raw"] for span in plan.spans if span["id"] not in used_spans]
    if unbound:
        warnings.append("Не удалось связать с характеристиками: " + ", ".join(unbound) + ".")
    supported = [c for c in candidates if c.status == "supported"]
    survivors = [c for c in candidates if c.status != "rejected"]
    uncertain_candidates = [c for c in survivors if c.status == "uncertain"]
    if uncertain_candidates:
        warnings.append("Есть неопределённые альтернативы; они сохранены для проверки, но не подтверждены.")
    recommended = (supported[0].position if len(supported) == 1 and complete
                   and not unresolved and not uncertain_candidates else None)
    status: AnalysisStatus
    if not candidates:
        status, question = "retrieval_miss", "Уточните наименование и назначение товара или область поиска: кандидаты не найдены."
    elif not complete:
        status, question = "incomplete_inference", "Завершите проверку характеристик: отсутствующие ответы нельзя считать отрицанием."
    elif not survivors:
        status, question = "no_compatible_shortlist_candidate", "Проверьте указанные противоречия; также может потребоваться расширить поиск кандидатов."
    elif unresolved or uncertain_candidates:
        status, question = "needs_clarification", "Уточните вид товара и неоднозначные характеристики перед исключением кандидатов."
    elif len(supported) == 1 and not supported[0].missing_required:
        status, question = "ready_for_review", None
    else:
        status = "needs_clarification"
        missing_names = sorted({char.name for c in supported for char in c.missing_required})
        question = ("Укажите «" + missing_names[0] + "»." if missing_names else
                    "Уточните вид и назначение товара: " + "; ".join(sorted({c.position.name for c in survivors})) + ".")
    return Report(plan, status, complete, recommended, candidates, sorted(properties), question,
                  warnings, answers, threshold)
