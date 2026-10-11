/** Mirrors backend/src/schemas.py (FastAPI contracts). */

export type AnalysisStatus =
  | 'retrieval_miss'
  | 'incomplete_inference'
  | 'no_compatible_shortlist_candidate'
  | 'needs_clarification'
  | 'ready_for_review'

export type CandidateStatus = 'compatible' | 'uncertain' | 'rejected'

export type ModelChoice = 'supported' | 'contradicted' | 'unknown' | 'conflicting'

export type ExtraAction =
  'map_and_validate' | 'do_not_add' | 'review_before_add' | 'additional_field_policy_unknown'

export type AnalysisScope = 'all' | 'drills' | 'tools' | 'clothing' | 'furniture'

export interface Property {
  name: string
  value: string
}

export interface ExtraCharacteristicInput {
  name: string
  value: string
}

export interface ExtraPropertyDecision {
  name: string
  value: string
  action: ExtraAction
}

export interface Candidate {
  code: string
  version: string
  name: string
  status: CandidateStatus
  reasons: string[]
  /** Uncalibrated product identity evidence; may be absent in partial or older results. */
  choice?: ModelChoice | null
  probabilities?: Record<ModelChoice, number> | null
  missing_required: string[]
  unmatched_properties: string[]
  extra_characteristics: ExtraPropertyDecision[]
}

export interface AnalysisRequest {
  text: string
  scope?: AnalysisScope
  top_k?: number
  chunk_size?: number
  threshold?: number
  extras?: ExtraCharacteristicInput[]
}

export interface AnalysisResponse {
  run_id: string
  status: AnalysisStatus
  complete_inference: boolean
  recommended_candidate: string | null
  properties: Property[]
  candidates: Candidate[]
  clarifying_question: string | null
  warnings: string[]
}

export interface CandidateReference {
  code: string
  version: string
  name: string
}

export interface PreviewResponse {
  planned_requests: number
  planned_questions: number
  candidates: CandidateReference[]
}

export interface HealthPayload {
  status: string
  model_busy: boolean
}

export interface HistoryAddRequest {
  session_id: string
  query: string
}

export interface HistoryResponse {
  queries: string[]
}
