import type { AnalysisResponse, Candidate } from './types'

function withArrayDefaults(candidate: Candidate): Candidate {
  return {
    ...candidate,
    reasons: candidate.reasons ?? [],
    missing_required: candidate.missing_required ?? [],
    unmatched_properties: candidate.unmatched_properties ?? [],
    extra_characteristics: candidate.extra_characteristics ?? [],
  }
}

/** The backend omits empty-default fields (response_model_exclude_defaults);
 * the UI expects every list to exist. */
export function normalizeAnalysis(raw: AnalysisResponse): AnalysisResponse {
  return {
    ...raw,
    properties: raw.properties ?? [],
    candidates: (raw.candidates ?? []).map(withArrayDefaults),
    warnings: raw.warnings ?? [],
  }
}
