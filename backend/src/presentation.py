"""Convert detailed pipeline evidence into a readable API result."""

from decimal import Decimal

from experiments.classifier_experiments import UNIT_SYMBOLS, canonical_value, normalize

from backend.src.schemas import AnalysisResponse, Candidate, Property


def describe_fact(fact: dict) -> str:
    return f"{fact['name']}: «{fact['value']}»"


def analysis_response(report: dict, run_id: str) -> AnalysisResponse:
    facts = {fact["id"]: fact for fact in report["categorical_facts"]}
    ambiguous = {fid for candidate in report["candidates"] for fid in candidate["uncertain"]}
    accepted = {(f["name"], canonical_value(f["name"], f["value"])) for fid, f in facts.items()
                if f["accepted"] and fid not in ambiguous}
    properties = [Property(name=name, value=value) for name, value in accepted]
    for binding in report["numeric_bindings"]:
        name = next((check["name"] for candidate in report["candidates"]
                     for check in candidate["numeric_checks"]
                     if check["span"] in binding["spans"] and normalize(check["name"]) == binding["name"]),
                    binding["name"])
        for span in binding["spans"]:
            value = format(Decimal(span["value"]).normalize(), "f")
            properties.append(Property(name=name, value=f"{value} {UNIT_SYMBOLS[binding['okei']]}"))

    candidates = []
    for candidate in report["candidates"]:
        reasons = []
        for fid in candidate["conflicts"]:
            reasons.append(describe_fact(facts[fid]) + " — значение не допускается этой позицией.")
        for check in candidate["numeric_checks"]:
            if check["status"] == "conflict":
                reasons.append(f"{check['name']}: {check['span']['raw']} — вне допустимых значений.")
            elif check["status"] == "uncertain":
                reasons.append(f"{check['name']}: правило каталога требует проверки.")
        answer = candidate["product_relevance"]
        if not candidate["object_supported"]:
            if answer and answer["choice"] == "contradicted" and answer["probabilities"]["contradicted"] >= report["threshold_uncalibrated"]:
                reasons.append("Указанный вид товара не соответствует описанию.")
            else:
                reasons.append("Вид товара не подтверждён описанием.")
        if candidate["uncertain"]:
            names = sorted({facts[fid]["name"] for fid in candidate["uncertain"]})
            reasons.append("Неоднозначные значения характеристик: " + ", ".join(names) + ".")
        if candidate["assessment"] == "compatible":
            reasons.append("Вид товара подтверждён, выполненные проверки характеристик пройдены.")
        candidates.append(Candidate(
            code=candidate["code"], version=candidate["version"], name=candidate["name"],
            status=candidate["assessment"], reasons=reasons,
            missing_required=[field["name"] for field in candidate["missing_required"]]
                             if candidate["assessment"] == "compatible" else [],
            unmatched_properties=sorted({facts[fid]["name"] for fid in candidate["extras"]}),
            extra_characteristics=[{key: extra[key] for key in ("name", "value", "action")}
                                   for extra in candidate["extra_characteristics"]],
        ))
    priority = {"compatible": 0, "uncertain": 1, "rejected": 2}
    candidates.sort(key=lambda candidate: (priority[candidate.status], candidate.code, candidate.version))
    recommended = next((f"{candidate.code}@{candidate.version}" for candidate in candidates
                        if candidate.status == "compatible" and candidate.code == report["provisional_candidate"]), None)
    warnings = []
    if ambiguous:
        warnings.append("Противоречивые принятые значения требуют уточнения: " +
                        ", ".join(sorted({facts[fid]["name"] for fid in ambiguous})) + ".")
    if any(candidate.status == "uncertain" for candidate in candidates):
        warnings.append("Есть неопределённые альтернативы; они сохранены для проверки, но не подтверждены.")
    if report["retrieval"]["truncated"]:
        warnings.append("Часть найденных позиций не вошла в список кандидатов.")
    for fact in facts.values():
        if fact["status"] == "conflicting":
            warnings.append(describe_fact(fact) + " — модель обнаружила противоречие в описании.")
    for conflict in report["unresolved_numeric"]:
        warnings.append(conflict["name"] + " — противоречивые числовые значения.")
    if report["unbound_measurements"]:
        warnings.append("Не удалось связать с характеристиками: " +
                        ", ".join(span["raw"] for span in report["unbound_measurements"]) + ".")
    return AnalysisResponse(
        run_id=run_id, status=report["status"], complete_inference=report["complete_inference"],
        recommended_candidate=recommended, requires_review=True,
        properties=sorted(properties, key=lambda item: (item.name, item.value)),
        candidates=candidates, clarifying_question=report["clarifying_question"], warnings=warnings,
    )
