"""API input limits and the complete explanation returned by the pipeline."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExtraCharacteristic(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=256)
    value: str = Field(min_length=1, max_length=2000)


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=10000)
    scope: Literal["all", "drills", "tools", "clothing", "furniture"] = "all"
    top_k: int = Field(default=8, ge=1, le=32)
    chunk_size: int = Field(default=4, ge=1, le=8)
    threshold: float = Field(default=0.8, ge=0, le=1, allow_inf_nan=False)
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


class AnalysisReport(BaseModel):
    status: Literal["retrieval_miss", "incomplete_inference",
                    "no_compatible_shortlist_candidate", "needs_clarification"]
    final_code: None
    provisional_candidate: str | None
    input: str
    retrieval: dict[str, Any]
    complete_inference: bool
    threshold_uncalibrated: float
    categorical_facts: list[dict[str, Any]]
    numeric_bindings: list[dict[str, Any]]
    unbound_measurements: list[dict[str, Any]]
    unresolved_numeric: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    clarifying_question: str
    limits: list[str]


class PipelineResponse(BaseModel):
    mode: Literal["preview", "live"]
    run_id: str | None
    catalog_sha256: str
    planned_requests: int
    planned_questions: int
    successful_requests: int
    analysis: AnalysisReport


class FailureDetail(BaseModel):
    error: str
    result: PipelineResponse | None = None


class ErrorResponse(BaseModel):
    detail: FailureDetail


class HealthResponse(BaseModel):
    status: Literal["ok"]
    catalog_positions: int
    catalog_facts: int
    model_busy: bool
    model: str
    model_readiness: Literal["not_checked"]


class ModelHealthResponse(BaseModel):
    status: Literal["ok"]
    upstream: dict[str, Any]
