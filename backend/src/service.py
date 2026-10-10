"""Reuse the experiment code, retain evidence, and serialize model access."""

from datetime import datetime, timezone
import json
from threading import Lock
from uuid import uuid4

from experiments import nimble_experiments as ne
from experiments import nimble_pipeline as pipeline

from backend.src.schemas import AnalysisRequest, PipelineResponse
from backend.src.settings import Settings


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
    return ne.load_catalog()


class PipelineService:
    def __init__(self, settings, catalog, client_factory=ne.SystemOneClient):
        self.settings = settings
        self.catalog = catalog
        self.client_factory = client_factory
        self.model_lock = Lock()

    def prepare(self, request: AnalysisRequest) -> dict:
        try:
            return pipeline.prepare(self.catalog, request.text, request.scope,
                                    request.top_k, request.chunk_size,
                                    self.settings.max_questions)
        except ValueError as error:
            message = str(error).replace("--max-questions", "BACKEND_MAX_QUESTIONS")
            raise InvalidPlan(message.replace("--top-k", "top_k").replace("--scope", "scope")) from error

    def result(self, request, plan, records, mode, run_id=None) -> PipelineResponse:
        return PipelineResponse(
            mode=mode, run_id=run_id, catalog_sha256=plan["catalog_sha256"],
            planned_requests=len(plan["jobs"]), planned_questions=plan["question_count"],
            successful_requests=sum("response" in record for record in records),
            analysis=pipeline.analyze(plan, records, request.threshold, request.confirmed_extras()),
        )

    def preview(self, request: AnalysisRequest) -> PipelineResponse:
        plan = self.prepare(request)
        return self.result(request, plan, [], "preview")

    def model_health(self) -> dict:
        if not self.model_lock.acquire(blocking=False):
            raise ModelBusy("A model request is already running; try again after it finishes")
        try:
            client = self.client_factory(self.settings.base_url,
                                         min(5, self.settings.timeout_seconds))
            try:
                return client.health()
            except (RuntimeError, ValueError) as error:
                raise InferenceFailure(str(error)) from error
        finally:
            self.model_lock.release()

    def analyze(self, request: AnalysisRequest) -> PipelineResponse:
        plan = self.prepare(request)
        if not self.model_lock.acquire(blocking=False):
            raise ModelBusy("A model request is already running; try again after it finishes")
        try:
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid4().hex
            output = self.settings.results_dir / run_id
            records = []
            failure = None
            if plan["jobs"]:
                client = self.client_factory(self.settings.base_url, self.settings.timeout_seconds)
                try:
                    records, _ = ne.run_jobs(client, plan["jobs"], output,
                                            self.catalog, request.threshold, request.scope)
                except (RuntimeError, ValueError) as error:
                    # The runner saves startup_error.json when the health check fails.
                    failure = str(error)
                failure = failure or next((r["error"] for r in records if "error" in r), None)
            else:
                output.mkdir(parents=True, exist_ok=False)
            result = self.result(request, plan, records, "live", run_id)
            for name, data in (("analysis.json", result.model_dump(mode="json")),
                               ("request_plan.json", plan["jobs"])):
                (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
            if failure:
                raise InferenceFailure(failure, result)
            return result
        finally:
            self.model_lock.release()
