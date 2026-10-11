"""Render typed product assessments using the unchanged public API schemas."""

from backend.src.pipeline import Report
from backend.src.schemas import AnalysisResponse, Candidate, ExtraPropertyDecision, Property


def analysis_response(report: Report, run_id: str) -> AnalysisResponse:
    candidates = [Candidate(
        code=candidate.position.code, version=str(candidate.position.version), name=candidate.position.name,
        status=candidate.status, reasons=candidate.reasons,
        missing_required=list(dict.fromkeys(char.name for char in candidate.missing_required))
                         if candidate.status == "supported" else [],
        unmatched_properties=sorted({h.name for h in candidate.unmatched}),
        extra_characteristics=[ExtraPropertyDecision.model_validate(
            {key: extra[key] for key in ("name", "value", "action")}) for extra in candidate.extras],
    ) for candidate in report.candidates]
    priority = {"compatible": 0, "uncertain": 1, "rejected": 2}
    candidates.sort(key=lambda candidate: (priority[candidate.status], candidate.code, candidate.version))
    recommended = report.recommended
    return AnalysisResponse(
        run_id=run_id, status=report.status, complete_inference=report.complete_inference,
        recommended_candidate=f"{recommended.code}@{recommended.version}" if recommended is not None else None,
        requires_review=True, properties=[Property(name=name, value=value) for name, value in report.properties],
        candidates=candidates, clarifying_question=report.clarifying_question, warnings=report.warnings,
        detected_families=report.families,
    )
