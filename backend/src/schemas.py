"""Small, typed API contracts; detailed model evidence is saved separately."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from experiments.config import env


class ExtraCharacteristic(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=256)
    value: str = Field(min_length=1, max_length=2000)


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=10000)
    scope: Literal["all", "drills", "tools", "clothing", "furniture"] = "all"
    top_k: int = Field(default=int(env("PIPELINE_TOP_K")), ge=1, le=32)
    chunk_size: int = Field(default=int(env("PIPELINE_CHUNK_SIZE")), ge=1, le=8)
    threshold: float = Field(default=float(env("PIPELINE_THRESHOLD")), ge=0, le=1, allow_inf_nan=False)
    extras: list[ExtraCharacteristic] = Field(default_factory=list, max_length=50)

    @field_validator("text")
    @classmethod
    def nonblank_text(cls, value):
        if not value.strip():
            raise ValueError("text must contain a product description")
        # Preserve offsets into the original input for measurement evidence.
        return value

    def confirmed_extras(self):
        return [dict(extra.model_dump(), origin="user_supplied") for extra in self.extras]


class CandidateReference(BaseModel):
    code: str
    version: str
    name: str


class Property(BaseModel):
    name: str
    value: str


class ExtraPropertyDecision(Property):
    action: Literal["map_and_validate", "do_not_add", "review_before_add", "additional_field_policy_unknown"]


class Candidate(CandidateReference):
    status: Literal["compatible", "uncertain", "rejected"]
    reasons: list[str]
    missing_required: list[str] = Field(default_factory=list)
    unmatched_properties: list[str] = Field(default_factory=list)
    extra_characteristics: list[ExtraPropertyDecision] = Field(default_factory=list)

    @field_validator("status", mode="before")
    @classmethod
    def normalize_legacy_status(cls, value):
        # Saved results from before the rename must still be readable.
        return "compatible" if value == "supported" else value


class PreviewResponse(BaseModel):
    planned_requests: int
    planned_questions: int
    candidates: list[CandidateReference]
    warnings: list[str] = Field(default_factory=list)


class SplitOption(BaseModel):
    text: str | None
    spans: list[dict] | None
    okei: str | None
    issue: str | None
    children: list[str]


class SplittingCharacteristic(BaseModel):
    code: str
    name: str
    required: bool
    is_numeric: bool
    resolved: bool
    observed: bool
    options: list[SplitOption]


class DetectedFamily(CandidateReference):
    is_template: Literal[True] = True
    resolved: bool
    candidate_codes: list[str]
    splitting_characteristics: list[SplittingCharacteristic]


class AnalysisResponse(BaseModel):
    run_id: str
    status: Literal["retrieval_miss", "incomplete_inference", "no_compatible_shortlist_candidate",
                    "needs_clarification", "ready_for_review"]
    complete_inference: bool
    recommended_candidate: str | None
    requires_review: Literal[True]
    properties: list[Property]
    candidates: list[Candidate]
    clarifying_question: str | None
    warnings: list[str]
    detected_families: list[DetectedFamily] = Field(default_factory=list)


class FailureDetail(BaseModel):
    error: str
    result: AnalysisResponse | None = None


class AnalysisJobResponse(BaseModel):
    run_id: str
    status: Literal["running", "completed", "failed"]
    result: AnalysisResponse | None = None
    error: str | None = None


class ErrorResponse(BaseModel):
    detail: FailureDetail


class HealthResponse(BaseModel):
    status: Literal["ok"]
    model_busy: bool


class ModelHealthResponse(BaseModel):
    status: Literal["ok"]
    model: str


class HistoryAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    session_id: str = Field(min_length=1, max_length=64)
    query: str = Field(min_length=1, max_length=500)


class HistoryResponse(BaseModel):
    queries: list[str]
