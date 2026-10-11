"""Plan against detached ORM records, retain evidence and serialize model access."""

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
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
        self.analysis_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
        self.jobs_lock = Lock()
        self.jobs = OrderedDict()
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
            plan = pipeline.prepare(retrieval, request.text, chunk_size, self.settings.max_questions)
            budget = plan.retrieval.details.get("question_budget")
            if budget:
                logger.warning("Analysis plan adjusted to question budget: %s", budget)
            return plan
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
            warnings=pipeline.budget_warnings(plan),
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
            try:
                self.store.start_model_call(run_id, index, outgoing)
            except Exception as e:
                logger.warning("Could not persist start_model_call for run_id=%s batch=%d: %s", run_id, index, e)
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
            try:
                self.store.finish_model_call(run_id, index, record)
            except Exception as e:
                logger.warning("Could not persist finish_model_call for run_id=%s batch=%d: %s", run_id, index, e)
            if failure:
                break  # Never retry a timed-out call: it may still own the shared GPU.
        try:
            self.store.save_artifact(run_id, "summary.json", {
                "planned_requests": len(requests), "completed_requests": len(records),
                "successful_requests": sum("response" in record for record in records),
                "stopped_early": len(records) < len(requests), "error": failure})
        except Exception as e:
            logger.warning("Could not save summary.json artifact for run_id=%s: %s", run_id, e)
        return records, failure

    def _reserve_run(self) -> str:
        if not self.model_lock.acquire(blocking=False):
            raise ModelBusy("A model request is already running; try again after it finishes")
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid4().hex

    def start_analysis(self, request: AnalysisRequest) -> str:
        """Reserve and persist a run for the synchronous endpoint."""
        run_id = self._reserve_run()
        try:
            self.store.begin_run(run_id, request.model_dump(mode="json"))
        except BaseException:
            self.model_lock.release()
            raise
        logger.info("Analysis started: run_id=%s", run_id)
        return run_id

    def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        return self._analyze_started(request, self.start_analysis(request))

    def submit_analysis(self, request: AnalysisRequest) -> str:
        run_id = self._reserve_run()
        self._update_job(run_id, status="running", result=None, error=None)
        try:
            # Schedule before sending HTTP headers: even a failed delivery of
            # the 202 response must not leave a reserved model lock orphaned.
            self.analysis_worker.submit(self._persist_analysis, request, run_id)
        except BaseException as error:
            self._update_job(run_id, status="failed", result=None, error=str(error))
            self.model_lock.release()
            raise
        return run_id

    def _update_job(self, run_id: str, **state) -> None:
        with self.jobs_lock:
            self.jobs[run_id] = {"id": run_id, **state}
            # Keep polling independent of slow database calls, with bounded memory.
            while len(self.jobs) > 32:
                self.jobs.popitem(last=False)

    def get_analysis_job(self, run_id: str) -> dict | None:
        with self.jobs_lock:
            cached = self.jobs.get(run_id)
        return dict(cached) if cached is not None else self.store.get_run(run_id)

    def _persist_analysis(self, request: AnalysisRequest, run_id: str) -> None:
        try:
            self.store.begin_run(run_id, request.model_dump(mode="json"))
        except Exception as error:
            self._update_job(run_id, status="failed", result=None, error=str(error))
            self.model_lock.release()
            logger.exception("Could not persist analysis: run_id=%s", run_id)
            return
        logger.info("Analysis started: run_id=%s", run_id)
        self.analyze_in_background(request, run_id)

    def close(self) -> None:
        self.analysis_worker.shutdown(wait=True)

    def analyze_in_background(self, request: AnalysisRequest, run_id: str) -> None:
        # The HTTP response has already been sent. Failures are persisted by the
        # worker and reported by polling, rather than raised through ASGI.
        try:
            result = self._analyze_started(request, run_id)
            self._update_job(run_id, status="completed", result=result.model_dump(mode="json"), error=None)
        except Exception as error:
            partial = error.result if isinstance(error, InferenceFailure) else None
            self._update_job(run_id, status="failed", error=str(error),
                             result=partial.model_dump(mode="json") if partial else None)
            logger.exception("Background analysis failed: run_id=%s", run_id)

    def _analyze_started(self, request: AnalysisRequest, run_id: str) -> AnalysisResponse:
        token = current_run.set(run_id)
        finalized = False
        try:
            started = perf_counter()
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
            if not finalized:
                try:
                    self.store.fail_run(run_id, error)
                except Exception:
                    logger.exception("Could not save failure for run_id=%s", run_id)
            raise
        finally:
            current_run.reset(token)
            self.model_lock.release()
