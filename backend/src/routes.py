"""HTTP routes with request validation and response contracts from schemas.py."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from backend.src.schemas import (
    AnalysisRequest,
    AnalysisResponse,
    ErrorResponse,
    HealthResponse,
    HistoryAddRequest,
    HistoryResponse,
    ModelHealthResponse,
    PreviewResponse,
)
from backend.src.history import SearchHistoryStore
from backend.src.service import PipelineService

router = APIRouter()

MODEL_ERRORS = {
    502: {
        "model": ErrorResponse,
        "description": "Embedding retrieval or classifier failed. detail.error explains the failure; "
                       "detail.result contains a saved partial analysis when available.",
    },
    503: {
        "model": ErrorResponse,
        "description": "PostgreSQL is unavailable, or another classifier operation holds the backend's model lock. "
                       "A busy-model response includes Retry-After: 5.",
    },
}


def get_pipeline_service(request: Request) -> PipelineService:
    return request.app.state.pipeline


PipelineDependency = Annotated[PipelineService, Depends(get_pipeline_service)]


def get_history_store(request: Request) -> SearchHistoryStore:
    return request.app.state.history


HistoryDependency = Annotated[SearchHistoryStore, Depends(get_history_store)]


@router.get("/health", tags=["Health"], summary="Check backend availability and classifier activity")
def health(service: PipelineDependency) -> HealthResponse:
    """Return a lightweight availability check after backend startup.

    - `status: "ok"` means the application has started and its pipeline is available.
    - `model_busy` reports whether a classifier analysis or health probe currently
      holds this backend instance's model lock. It does not report GPU utilization
      or activity from other clients of the classifier server.

    This endpoint performs no database queries, embedding calls or classifier
    calls. A successful response does not verify current upstream connectivity;
    use `/health/model` to check the classifier separately.
    """
    return HealthResponse(
        status="ok",
        model_busy=service.model_lock.locked(),
    )


@router.get(
    "/health/model", tags=["Health"], summary="Check classifier connectivity and model identity",
    responses={
        502: {"model": ErrorResponse, "description": "Classifier health request failed or returned an unexpected model identity."},
        503: {"model": ErrorResponse, "description": "Another classifier operation is running. Retry-After: 5 is returned."},
    },
)
def model_health(service: PipelineDependency) -> ModelHealthResponse:
    """Call the configured classifier's health endpoint and verify its model identity.

    Returns `status: "ok"` and the model name when the upstream service responds
    with the expected model. The timeout is the smaller of
    `CLASSIFIER_HEALTH_TIMEOUT_SECONDS` and `CLASSIFIER_TIMEOUT_SECONDS`.

    This probe briefly takes the same lock as `/analyze`; it returns `503` if
    another classifier operation is running. Connection failures, timeouts and
    unexpected model identities return `502` with an explanation in `detail.error`.

    No inference, embedding search or analysis-run creation is performed. This
    endpoint does not check the embedder or database connectivity.
    """
    return ModelHealthResponse(status="ok", model=service.model_health()["model"])


@router.post(
    "/preview", tags=["Pipeline"], summary="Preview semantic candidates and classifier request counts",
    responses={
        502: {"model": ErrorResponse, "description": "Embedding retrieval failed; no classifier inference was attempted."},
        503: {"model": ErrorResponse, "description": "PostgreSQL is unavailable."},
    },
)
def preview(body: AnalysisRequest, service: PipelineDependency) -> PreviewResponse:
    """Search the loaded KTRU catalogue and prepare an analysis plan without scoring it.

    Send the same request body as `/analyze`; only `text` is required. `scope`
    selects the catalogue subset and `top_k` limits the retrieved positions.
    `scope: "all"` means the loaded snapshot, not the entire KTRU catalogue.

    The response contains:

    - `candidates`: retrieved code, version and name. These are semantic search
      results; product relevance and characteristic compatibility have not yet
      been checked.
    - `planned_requests`: the number of classifier HTTP requests after batching.
    - `planned_questions`: the total number of individual classifier questions.

    `chunk_size` controls logical categorical-question groups; HTTP packing is
    controlled by `CLASSIFIER_BATCH_SIZE`. `threshold` and `extras` are accepted
    for consistency with `/analyze` but do not affect this preview.

    The embedder is called to encode the description. Catalogue embeddings are
    built and cached in PostgreSQL when the matching index is missing, so the
    first request can take longer. No classifier inference or analysis-run record
    is created. Preview can run while the classifier is busy.

    Invalid input or a plan exceeding the configured question budget returns
    `422`; embedding failures return `502`; database failures return `503`.
    """
    return service.preview(body)


@router.post(
    "/analyze", tags=["Pipeline"], summary="Analyze a description and explain KTRU candidate compatibility",
    responses=MODEL_ERRORS, response_model_exclude_defaults=True,
)
def analyze(body: AnalysisRequest, service: PipelineDependency) -> AnalysisResponse:
    """Turn a product description into interpreted properties and explained candidates.

    Only `text` is required. Optional inputs are:

    - `scope`: `all`, `drills`, `tools`, `clothing` or `furniture`. Search is limited
      to the loaded catalogue snapshot.
    - `top_k`: maximum retrieved positions (1–32).
    - `chunk_size`: categorical questions per logical group (1–8).
    - `threshold`: acceptance cutoff for model answers (0–1); this is an
      experimental, uncalibrated confidence threshold.
    - `extras`: caller-supplied name/value properties to assess against each
      candidate's additional-characteristic policy. They do not automatically
      complete required fields or override extracted facts.

    The backend retrieves candidates using embeddings, asks the classifier about
    product identity and categorical facts, binds numerical measurements to
    properties, and checks allowed catalogue values and numeric bounds. Classifier
    questions are packed into HTTP batches, which are sent sequentially.

    **Interpret the response:**

    - `properties` contains accepted categorical values and normalized measurements.
    - Each candidate includes `reasons` and a status: `compatible` means product
      identity is established and performed checks passed; `uncertain` means the
      evidence is insufficient; `rejected` means a definite conflict was found.
      Several candidates can be compatible, and required fields can still be
      missing. `missing_required` lists those fields for compatible candidates.
    - `recommended_candidate` is a provisional `code@version`, or `null` when no
      unique candidate satisfies the recommendation checks.
    - `status` is `needs_clarification`, `ready_for_review`, `retrieval_miss`,
      `no_compatible_shortlist_candidate` or `incomplete_inference`.
      `clarifying_question` and `warnings` explain the next step.
    - `complete_inference` means all planned classifier jobs returned answers;
      it does not mean all required specifications or applicability rules are
      validated. `requires_review` is always `true`; no final KTRU code is issued.

    The request, plan, model evidence and result are saved in PostgreSQL. Use the
    returned `run_id` with `/results/{run_id}` to read the saved response. Empty
    optional candidate lists are omitted from the response.

    This is a synchronous, potentially long-running operation. Only one classifier
    operation runs at a time per backend instance; a competing request returns
    `503` with `Retry-After: 5`. Invalid input or an excessive question budget
    returns `422`. Upstream failures return `502`; `detail.result` contains a
    partial saved analysis when available. Missing answers are not negative facts,
    and failed model calls are not automatically retried. Database failures return
    `503`.

    A browser disconnect can occur while processing continues. Recover the run ID
    from backend logs and read `/results/{run_id}` after the result is saved.
    Resubmitting `/analyze` creates a new run; it does not resume a prior run or
    maintain a clarification session. Include any clarification in the new text.
    """
    return service.analyze(body)


@router.get(
    "/results/{run_id}", tags=["Pipeline"], summary="Read a saved analysis or recover a disconnected request",
    response_model_exclude_defaults=True,
    responses={
        404: {"model": ErrorResponse, "description": "Run is unknown or no result has been saved, including runs still processing."},
        503: {"model": ErrorResponse, "description": "PostgreSQL is unavailable."},
    },
)
def saved_result(
    run_id: Annotated[str, Path(pattern=r"^[0-9]{8}T[0-9]{12}Z_[0-9a-f]{32}$")],
    service: PipelineDependency,
) -> AnalysisResponse:
    """Return the analysis response already stored for the specified run.

    Use the `run_id` returned by `/analyze` or recorded in backend logs. The ID
    contains a UTC timestamp and a hexadecimal UUID, for example
    `20261010T205209275161Z_280af0883a6f4f318121d014620370df`.

    The response has the same schema and interpretation as `/analyze`, including
    candidate reasons, missing requirements, warnings and any provisional
    recommendation. A saved partial analysis is also returned with `200`; check
    `complete_inference` and `status` before interpreting it. Older saved candidate
    statuses named `supported` are returned as `compatible`.

    This endpoint reads PostgreSQL only. It does not call either model, create an
    analysis run, resume failed work or modify saved evidence. It remains available
    while the classifier is busy and can recover a response lost after a browser
    disconnect.

    `404` means the run is unknown or has no saved result yet; a still-processing
    run can return `404`. A malformed run ID returns `422`. Database failures
    return `503`.
    """
    run = service.store.get_run(run_id)
    if run is None or run["result"] is None:
        raise HTTPException(404, detail={"error": "Run is unknown or its result is not saved yet"})
    return AnalysisResponse.model_validate(run["result"])


@router.post(
    "/history", tags=["History"], summary="Save a search query to session history",
)
def add_history(
    body: HistoryAddRequest,
    history: HistoryDependency,
) -> None:
    """Store a search query under the given session ID.

    The query is prepended to the session's list (newest first), duplicates are
    removed, and the list is trimmed to the configured maximum (default 5).
    Keys expire after the configured TTL (default 7 days).

    Returns 200 on success even when Redis is unavailable — history is
    best-effort. No content body.
    """
    history.add(body.session_id, body.query)


@router.get(
    "/history/{session_id}", tags=["History"], summary="Get recent search queries for a session",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid session ID format."},
    },
)
def get_history(
    session_id: Annotated[str, Path(min_length=1, max_length=64)],
    history: HistoryDependency,
) -> HistoryResponse:
    """Return the most recent queries for a session, newest first.

    Returns an empty list when the session has no history or Redis is
    unavailable. Session IDs must match `[A-Za-z0-9_-]{1,64}`.
    """
    return HistoryResponse(queries=history.get(session_id))
