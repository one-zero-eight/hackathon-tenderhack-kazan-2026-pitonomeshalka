"""ASGI application assembly, catalog lifespan and HTTP error handling."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from psycopg import Error as DatabaseError
from psycopg_pool import PoolTimeout

from experiments import classifier_experiments as ce
from experiments.embedding_retrieval import MeowEmbedClient

from backend.src.routes import router
from backend.src.service import InferenceFailure, InvalidPlan, ModelBusy, PipelineService, load_catalog
from backend.src.settings import Settings
from backend.src.startup import check_connections
from backend.src.storage import PostgresStore


def model_busy_handler(request: Request, error: ModelBusy) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": {"error": str(error)}},
        headers={"Retry-After": "5"},
    )


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
    catalog_loader=load_catalog,
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
            catalog = await run_in_threadpool(store.get_catalog, configuration.catalog_key)
            if catalog is None:
                catalog = await run_in_threadpool(catalog_loader, configuration)
                await run_in_threadpool(store.save_catalog, catalog, configuration.catalog_key)
                logging.getLogger("uvicorn.error").info("Catalog imported into PostgreSQL: positions=%d facts=%d",
                                                       len(catalog["positions"]), len(catalog["facts"]))
            application.state.pipeline = PipelineService(configuration, catalog, client_factory,
                                                          embedding_client_factory, store=store)
            yield
        finally:
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
    def database_error_handler(request, error):
        logging.getLogger("uvicorn.error").exception("PostgreSQL request failed")
        return JSONResponse(status_code=503, content={"detail": {"error": "Database unavailable"}})
    application.add_exception_handler(DatabaseError, database_error_handler)
    application.add_exception_handler(PoolTimeout, database_error_handler)
    application.include_router(router)
    return application


app = create_app()
