"""ASGI application assembly, catalog lifespan and HTTP error handling."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from experiments import nimble_experiments as ne

from backend.src.routes import router
from backend.src.service import InferenceFailure, InvalidPlan, ModelBusy, PipelineService, load_catalog
from backend.src.settings import Settings


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
    client_factory=ne.SystemOneClient,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        configuration = settings or Settings.from_environment()
        catalog = await run_in_threadpool(catalog_loader, configuration)
        application.state.pipeline = PipelineService(configuration, catalog, client_factory)
        yield

    application = FastAPI(
        title="Explained KTRU candidates",
        version="0.1.0",
        lifespan=lifespan,
        description="Find and explain provisional KTRU candidates using the existing Nimble pipeline. "
                    "Missing fields and uncertainties remain visible; no final validated code is issued.",
    )
    application.add_exception_handler(ModelBusy, model_busy_handler)
    application.add_exception_handler(InferenceFailure, inference_failure_handler)
    application.add_exception_handler(InvalidPlan, invalid_plan_handler)
    application.include_router(router)
    return application


app = create_app()
