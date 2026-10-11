import type { AnalysisResponse, Candidate, Clarification } from './types'

function withArrayDefaults(candidate: Candidate): Candidate {
  return {
    ...candidate,
    reasons: candidate.reasons ?? [],
    missing_required: candidate.missing_required ?? [],
    unmatched_properties: candidate.unmatched_properties ?? [],
    extra_characteristics: candidate.extra_characteristics ?? [],
  }
}

function withOptionDefaults(clarification: Clarification): Clarification {
  return {
    ...clarification,
    options: (clarification.options ?? []).map((option) => ({
      ...option,
      candidate_codes: option.candidate_codes ?? [],
    })),
  }
}

/** The backend omits empty-default fields (response_model_exclude_defaults);
 * the UI expects every list to exist. The final card is catalogue data and
 * passes through untouched. */
export function normalizeAnalysis(raw: AnalysisResponse): AnalysisResponse {
  return {
    ...raw,
    properties: raw.properties ?? [],
    candidates: (raw.candidates ?? []).map(withArrayDefaults),
    warnings: raw.warnings ?? [],
    clarification: raw.clarification ? withOptionDefaults(raw.clarification) : undefined,
    final_card: raw.final_card,
    suggest_expand: raw.suggest_expand ?? false,
    manual_choice: raw.manual_choice ?? false,
  }
}
