"""Reuse the experiment code, retain evidence, and serialize model access."""

from datetime import datetime, timezone
import json
import logging
from threading import Lock
from time import perf_counter
from uuid import uuid4

from experiments import classifier_experiments as ce
from experiments import classifier_pipeline as pipeline
from experiments.embedding_retrieval import EmbeddingError, EmbeddingRetriever, MeowEmbedClient

from backend.src.presentation import analysis_response
from backend.src.schemas import AnalysisRequest, AnalysisResponse, CandidateReference, PreviewResponse
from backend.src.settings import Settings
from backend.src.storage import current_run

logger = logging.getLogger("uvicorn.error")


class ModelBusy(RuntimeError):
    pass


class InvalidPlan(ValueError):
    """The requested pipeline plan exceeds supported input or budget limits."""


class InferenceFailure(RuntimeError):
    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result


def load_catalog(settings: Settings):
    if settings.catalog_path.exists():
        return json.loads(settings.catalog_path.read_text(encoding="utf-8"))
    # Match the CLI: import the supplied XML if no cached snapshot exists.
    return ce.load_catalog(settings.xml_dir)


class PipelineService:
    def __init__(self, settings, catalog, client_factory=ce.ClassifierClient,
                 embedding_client_factory=MeowEmbedClient, *, store):
        self.settings = settings
        self.catalog = catalog
        self.client_factory = client_factory
        self.model_lock = Lock()
        self.store = store
        embedding_client = embedding_client_factory(settings.embedding_base_url, settings.embedding_model,
                                                    settings.embedding_timeout_seconds)
        embedding_client.recorder = store
        self.retriever = EmbeddingRetriever(
            catalog, embedding_client, None, settings.embedding_batch_size, settings.embedding_max_names,
            cache_store=store,
        )

    def prepare(self, request: AnalysisRequest) -> dict:
        try:
            retrieval = self.retriever.retrieve(self.catalog, request.text, request.scope, request.top_k)
            return pipeline.prepare(self.catalog, request.text, request.scope,
                                    request.top_k, request.chunk_size,
                                    self.settings.max_questions, retrieval=retrieval)
        except EmbeddingError as error:
            raise InferenceFailure("Embedding retrieval failed: " + str(error)) from error
        except ValueError as error:
            message = str(error).replace("--max-questions", "BACKEND_MAX_QUESTIONS")
            raise InvalidPlan(message.replace("--top-k", "top_k").replace("--scope", "scope")) from error

    def preview(self, request: AnalysisRequest) -> PreviewResponse:
        plan = self.prepare(request)
        return PreviewResponse(
            planned_requests=len(plan["jobs"]), planned_questions=plan["question_count"],
            candidates=[CandidateReference(code=p["code"], version=p["version"], name=p["name"])
                        for p in plan["retrieval"]["positions"]],
        )

    def model_health(self) -> dict:
        if not self.model_lock.acquire(blocking=False):
            raise ModelBusy("A model request is already running; try again after it finishes")
        try:
            client = self.client_factory(self.settings.classifier_base_url,
                                         min(self.settings.classifier_health_timeout_seconds, self.settings.classifier_timeout_seconds))
            try:
                return client.health()
            except (RuntimeError, ValueError) as error:
                raise InferenceFailure(str(error)) from error
        finally:
            self.model_lock.release()

    def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        if not self.model_lock.acquire(blocking=False):
            raise ModelBusy("A model request is already running; try again after it finishes")
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid4().hex
        token = current_run.set(run_id)
        saved = False
        finalized = False
        try:
            started = perf_counter()
            self.store.begin_run(run_id, request.model_dump(mode="json"))
            saved = True
            logger.info("Analysis started: run_id=%s", run_id)
            plan = self.prepare(request)
            self.store.save_catalog(self.catalog)
            self.store.save_plan(run_id, plan)
            logger.info("Analysis plan: run_id=%s requests=%d questions=%d", run_id,
                        len(plan["jobs"]), plan["question_count"])
            records = []
            failure = None
            if plan["jobs"]:
                client = self.client_factory(self.settings.classifier_base_url, self.settings.classifier_timeout_seconds)
                try:
                    records, _ = ce.run_jobs(client, plan["jobs"], None,
                                            self.catalog, request.threshold, request.scope,
                                            evidence_store=self.store, run_id=run_id)
                except (RuntimeError, ValueError) as error:
                    # The runner retains the health failure as a database artifact.
                    failure = str(error)
                failure = failure or next((r["error"] for r in records if "error" in r), None)
            report = pipeline.analyze(plan, records, request.threshold, request.confirmed_extras())
            result = analysis_response(report, run_id)
            details = dict(
                mode="live", run_id=run_id, catalog_sha256=plan["catalog_sha256"],
                planned_requests=len(plan["jobs"]), planned_questions=plan["question_count"],
                successful_requests=sum("response" in record for record in records), analysis=report,
            )
            self.store.finish_run(run_id, details, result.model_dump(mode="json", exclude_defaults=True), failure)
            finalized = True
            logger.info("Analysis saved: run_id=%s status=%s complete_inference=%s elapsed=%.3fs storage=postgresql",
                        run_id, result.status, result.complete_inference, perf_counter() - started)
            if failure:
                raise InferenceFailure(failure, result)
            return result
        except Exception as error:
            if saved and not finalized:
                try:
                    self.store.fail_run(run_id, error)
                except Exception:
                    logger.exception("Could not save failure for run_id=%s", run_id)
            raise
        finally:
            current_run.reset(token)
            self.model_lock.release()
