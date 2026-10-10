"""HTTP routes with request validation and response contracts from schemas.py."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from backend.src.schemas import (
    AnalysisRequest,
    AnalysisResponse,
    ErrorResponse,
    HealthResponse,
    ModelHealthResponse,
    PreviewResponse,
)
from backend.src.service import PipelineService

router = APIRouter()

MODEL_ERRORS = {
    502: {"model": ErrorResponse, "description": "Nimble failed; partial analysis is retained when available"},
    503: {"model": ErrorResponse, "description": "Another model request is running"},
}


def get_pipeline_service(request: Request) -> PipelineService:
    return request.app.state.pipeline


PipelineDependency = Annotated[PipelineService, Depends(get_pipeline_service)]


@router.get("/health", tags=["Health"])
def health(service: PipelineDependency) -> HealthResponse:
    """Check the backend and loaded catalog without contacting the model."""
    return HealthResponse(
        status="ok",
        model_busy=service.model_lock.locked(),
    )


@router.get("/health/model", tags=["Health"], responses=MODEL_ERRORS)
def model_health(service: PipelineDependency) -> ModelHealthResponse:
    """Probe Nimble separately with a timeout of at most five seconds."""
    return ModelHealthResponse(status="ok", model=service.model_health()["model"])


@router.post("/preview", tags=["Pipeline"])
def preview(body: AnalysisRequest, service: PipelineDependency) -> PreviewResponse:
    """Prepare the shortlist and question counts; perform no inference or writes."""
    return service.preview(body)


@router.post("/analyze", tags=["Pipeline"], responses=MODEL_ERRORS, response_model_exclude_defaults=True)
def analyze(body: AnalysisRequest, service: PipelineDependency) -> AnalysisResponse:
    """Run sequential model requests, check catalog constraints, and save evidence."""
    return service.analyze(body)
