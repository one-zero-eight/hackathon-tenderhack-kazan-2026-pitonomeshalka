"""Plan against detached ORM records, retain evidence and serialize model access."""

from datetime import datetime, timezone
import json
import logging
from threading import Lock
from time import perf_counter
from uuid import uuid4

from experiments import classifier_experiments as ce
from experiments.classifier_pipeline import batch_jobs, unpack_records
from experiments.embedding_retrieval import EmbeddingError, MeowEmbedClient

from backend.src import pipeline
from backend.src.presentation import analysis_response
from backend.src.schemas import AnalysisRequest, AnalysisResponse, CandidateReference, PreviewResponse
from backend.src.storage import current_run

logger = logging.getLogger("uvicorn.error")
MODEL_FAILURES = (RuntimeError, ValueError, OSError, TypeError, KeyError, AttributeError)


class ModelBusy(RuntimeError):
    pass


class InvalidPlan(ValueError):
    """The requested pipeline plan exceeds supported input or budget limits."""


class InferenceFailure(RuntimeError):
    def __init__(self, message, result=None):
        super().__init__(message)
        self.result = result


class PipelineService:
    def __init__(self, settings, client_factory=ce.ClassifierClient,
                 embedding_client_factory=MeowEmbedClient, *, store):
        from backend.src.retrieval import EmbeddingRetriever

        self.settings = settings
        self.client_factory = client_factory
        self.model_lock = Lock()
        self.store = store
        embedding_client = embedding_client_factory(settings.embedding_base_url, settings.embedding_model,
                                                    settings.embedding_timeout_seconds)
        embedding_client.recorder = store
        self.retriever = EmbeddingRetriever(store, settings, embedding_client)

    def prepare(self, request: AnalysisRequest) -> pipeline.Plan:
        try:
            retrieval = self.retriever.retrieve(request.text, request.scope, request.top_k)
            batch_size = self.settings.classifier_batch_size
            chunk_size = min(request.chunk_size, batch_size) if batch_size else request.chunk_size
            return pipeline.prepare(retrieval, request.text, chunk_size, self.settings.max_questions)
        except EmbeddingError as error:
            raise InferenceFailure("Embedding retrieval failed: " + str(error)) from error
        except ValueError as error:
            raise InvalidPlan(str(error)) from error

    def _requests(self, plan: pipeline.Plan) -> list[dict]:
        return batch_jobs([job.snapshot() for job in plan.jobs], self.settings.classifier_batch_size)

    def preview(self, request: AnalysisRequest) -> PreviewResponse:
        plan = self.prepare(request)
        return PreviewResponse(
            planned_requests=len(self._requests(plan)), planned_questions=plan.question_count,
            candidates=[CandidateReference(code=p.code, version=str(p.version), name=p.name)
                        for p in plan.retrieval.positions],
        )

    def model_health(self) -> dict:
        if not self.model_lock.acquire(blocking=False):
            raise ModelBusy("A model request is already running; try again after it finishes")
        try:
            client = self.client_factory(self.settings.classifier_base_url,
                                         min(self.settings.classifier_health_timeout_seconds,
                                             self.settings.classifier_timeout_seconds))
            try:
                return client.health()
            except MODEL_FAILURES as error:
                raise InferenceFailure(str(error)) from error
        finally:
            self.model_lock.release()

    def _run_jobs(self, plan: pipeline.Plan, requests: list[dict], run_id: str, threshold: float,
                  scope: str) -> tuple[list[dict], str | None]:
        if not requests:
            return [], None
        records = []
        try:
            client = self.client_factory(self.settings.classifier_base_url,
                                         self.settings.classifier_timeout_seconds)
            health = client.health()
        except MODEL_FAILURES as error:
            self.store.save_artifact(run_id, "startup_error.json", {
                "error": str(error), "base_url": self.settings.classifier_base_url})
            return records, str(error)
        self.store.save_artifact(run_id, "health.json", health)
        self.store.save_artifact(run_id, "manifest.json", {
            "model": ce.MODEL, "base_url": client.base_url, "timeout": client.timeout,
            "scope": scope, "threshold_uncalibrated": threshold,
            "import_sha256": plan.retrieval.import_sha256,
            "planned_requests": len(requests), "diagnostic_not_held_out": True})
        failure = None
        for index, job in enumerate(requests):
            record = {key: value for key, value in job.items() if key != "body"}
            outgoing = {
                "logged_at": datetime.now(timezone.utc).isoformat(),
                "id": job["id"], "experiment": job["experiment"], "method": "POST",
                "url": client.base_url.rstrip("/") + "/v1/systemone", "request": job["body"],
                "sources": {key: job[key] for key in ("parts", "facts", "bindings", "positions") if key in job},
            }
            # Commit before dispatch: interrupted or still-running GPU calls stay visible.
            self.store.start_model_call(run_id, index, outgoing)
            logger.info("Model request: %d/%d run_id=%s id=%s experiment=%s questions=%d",
                        index + 1, len(requests), run_id, job["id"], job["experiment"],
                        len(job["body"]["questions"]))
            logger.debug("Model request payload: %s", json.dumps(outgoing, ensure_ascii=False))
            started = perf_counter()
            try:
                # ClassifierClient.infer checks model, IDs, probabilities and selected choice.
                record.update(client.infer(job["body"]))
            except MODEL_FAILURES as error:
                failure = str(error)
                record.update(request=job["body"], error=failure, elapsed_seconds=perf_counter() - started)
            records.append(record)
            self.store.finish_model_call(run_id, index, record)
            if failure:
                break  # Never retry a timed-out call: it may still own the shared GPU.
        self.store.save_artifact(run_id, "summary.json", {
            "planned_requests": len(requests), "completed_requests": len(records),
            "successful_requests": sum("response" in record for record in records),
            "stopped_early": len(records) < len(requests), "error": failure})
        return records, failure

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
            requests = self._requests(plan)
            self.store.save_plan(run_id, dict(plan.snapshot(), requests=requests))
            logger.info("Analysis plan: run_id=%s requests=%d questions=%d", run_id,
                        len(requests), plan.question_count)
            records, failure = self._run_jobs(plan, requests, run_id, request.threshold, request.scope)
            report = pipeline.analyze(plan, unpack_records(records), request.threshold, request.confirmed_extras())
            result = analysis_response(report, run_id)
            details = dict(
                mode="live", run_id=run_id, import_sha256=plan.retrieval.import_sha256,
                planned_requests=len(requests), planned_questions=plan.question_count,
                successful_requests=sum("response" in record for record in records), analysis=report.snapshot(),
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
