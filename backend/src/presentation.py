"""Render typed product assessments using the unchanged public API schemas."""

from backend.src.clarify import build_clarification, initial_candidate_codes
from backend.src.pipeline import Report
from backend.src.schemas import AnalysisResponse, Candidate, ExtraPropertyDecision, Property


def analysis_response(report: Report, run_id: str) -> AnalysisResponse:
    """Candidates keep the report's own order (retrieval order); no status sorting."""
    candidates = [Candidate(
        code=candidate.position.code, version=str(candidate.position.version), name=candidate.position.name,
        status=candidate.status, reasons=candidate.reasons,
        missing_required=list(dict.fromkeys(char.name for char in candidate.missing_required))
                         if candidate.status == "supported" else [],
        unmatched_properties=sorted({h.name for h in candidate.unmatched}),
        extra_characteristics=[ExtraPropertyDecision.model_validate(
            {key: extra[key] for key in ("name", "value", "action")}) for extra in candidate.extras],
    ) for candidate in report.candidates]
    recommended = report.recommended
    return AnalysisResponse(
        run_id=run_id, status=report.status, complete_inference=report.complete_inference,
        recommended_candidate=f"{recommended.code}@{recommended.version}" if recommended is not None else None,
        requires_review=True, properties=[Property(name=name, value=value) for name, value in report.properties],
        candidates=candidates, clarifying_question=report.clarifying_question, warnings=report.warnings,
        detected_families=report.families,
    )


def clarification_response(result: dict, **fields) -> AnalysisResponse:
    """Rebuild the public response from the untouched saved result plus clarification fields."""
    return AnalysisResponse.model_validate({**result, **fields})


def with_primary_clarification(result: dict) -> AnalysisResponse:
    """Attach the round-one question to a fresh response; the saved result dict stays untouched."""
    codes = initial_candidate_codes(result)
    if result.get("status") == "needs_clarification" and len(codes) >= 2:
        return clarification_response(result, clarification=build_clarification(result, codes, 1))
    return AnalysisResponse.model_validate(result)
