"""HTTP routes with request validation and response contracts from schemas.py."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request

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
    502: {"model": ErrorResponse, "description": "Embedding retrieval or classifier failed; partial analysis is retained when available"},
    503: {"model": ErrorResponse, "description": "Database unavailable or another model request is running"},
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
    """Probe the classifier separately with a timeout of at most five seconds."""
    return ModelHealthResponse(status="ok", model=service.model_health()["model"])


@router.post("/preview", tags=["Pipeline"], responses={502: MODEL_ERRORS[502], 503: MODEL_ERRORS[503]})
def preview(body: AnalysisRequest, service: PipelineDependency) -> PreviewResponse:
    """Search with embeddings and prepare classifier questions; lazily cache catalog vectors."""
    return service.preview(body)


@router.post("/analyze", tags=["Pipeline"], responses=MODEL_ERRORS, response_model_exclude_defaults=True)
def analyze(body: AnalysisRequest, service: PipelineDependency) -> AnalysisResponse:
    """Run sequential model requests, check catalog constraints, and save evidence."""
    return service.analyze(body)


@router.get("/results/{run_id}", tags=["Pipeline"], response_model_exclude_defaults=True,
            responses={404: {"model": ErrorResponse, "description": "Run is unknown or its result is not saved yet"}})
def saved_result(
    run_id: Annotated[str, Path(pattern=r"^[0-9]{8}T[0-9]{12}Z_[0-9a-f]{32}$")],
    service: PipelineDependency,
) -> AnalysisResponse:
    """Read a saved result after a browser disconnect; never rerun retrieval or inference."""
    run = service.store.get_run(run_id)
    if run is None or run["result"] is None:
        raise HTTPException(404, detail={"error": "Run is unknown or its result is not saved yet"})
    return AnalysisResponse.model_validate(run["result"])
