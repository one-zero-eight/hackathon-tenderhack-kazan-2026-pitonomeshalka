"""ASGI application assembly, catalog lifespan and HTTP error handling."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from psycopg import Error as DatabaseError
from sqlalchemy.exc import SQLAlchemyError

from experiments import classifier_experiments as ce
from experiments.embedding_retrieval import MeowEmbedClient

from backend.src.history import SearchHistoryStore
from backend.src.routes import router
from backend.src.service import (
    ClarificationConflict,
    InferenceFailure,
    InvalidPlan,
    ModelBusy,
    PipelineService,
    UnknownRun,
)
from backend.src.settings import Settings
from backend.src.startup import check_connections
from backend.src.storage import PostgresStore


def model_busy_handler(request: Request, error: ModelBusy) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": {"error": str(error)}},
        headers={"Retry-After": "5"},
    )


def unknown_run_handler(request: Request, error: UnknownRun) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": {"error": str(error)}})


def clarification_conflict_handler(request: Request, error: ClarificationConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": {"error": str(error)}})


def inference_failure_handler(request: Request, error: InferenceFailure) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"detail": {
            "error": str(error),
            "result": error.result.model_dump(mode="json", exclude_defaults=True) if error.result else None,
        }},
    )


def invalid_plan_handler(request: Request, error: InvalidPlan) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": [{"loc": ["body"], "msg": str(error), "type": "value_error"}]},
    )


def create_app(
    settings: Settings | None = None,
    *,

    client_factory=ce.ClassifierClient,
    embedding_client_factory=MeowEmbedClient,
    store_factory=PostgresStore,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        configuration = settings or Settings.from_environment()
        store = store_factory(configuration)
        try:
            await run_in_threadpool(store.initialize)
            application.state.storage = store
            application.state.startup_connections = await check_connections(
                configuration, client_factory, embedding_client_factory, store,
            )
            active = await run_in_threadpool(store.get_active_import, configuration.catalog_key)
            if active is None:
                logging.getLogger("uvicorn.error").warning("No active catalogue; run scripts/load_db.py --activate %s", configuration.catalog_key)
            application.state.pipeline = PipelineService(configuration, client_factory,
                                                        embedding_client_factory, store=store)
            history = SearchHistoryStore(
                configuration.redis_url,
                max_items=configuration.history_max_items,
                ttl_seconds=configuration.history_ttl_seconds,
            )
            application.state.history = history
            yield
        finally:
            history.close()
            await run_in_threadpool(store.close)

    application = FastAPI(
        title="Explained KTRU candidates",
        version="0.1.0",
        lifespan=lifespan,
        description="Find and explain provisional KTRU candidates using the existing classifier pipeline. "
                    "Missing fields and uncertainties remain visible; no final validated code is issued.",
    )
    application.add_exception_handler(ModelBusy, model_busy_handler)
    application.add_exception_handler(InferenceFailure, inference_failure_handler)
    application.add_exception_handler(InvalidPlan, invalid_plan_handler)
    application.add_exception_handler(UnknownRun, unknown_run_handler)
    application.add_exception_handler(ClarificationConflict, clarification_conflict_handler)
    def database_error_handler(request, error):
        logging.getLogger("uvicorn.error").exception("PostgreSQL request failed")
        return JSONResponse(status_code=503, content={"detail": {"error": "Database unavailable"}})
    application.add_exception_handler(DatabaseError, database_error_handler)
    application.add_exception_handler(SQLAlchemyError, database_error_handler)
    application.include_router(router)
    return application


app = create_app()
