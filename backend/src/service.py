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
from backend.src.clarify import (CLARIFICATION_STATE, apply_option, build_clarification,
                                 initial_candidate_codes, next_required_question)
from backend.src.final_card import build_final_card
from backend.src.llm import LLMMappingError, RouterClient
from backend.src.presentation import analysis_response, clarification_response, with_primary_clarification
from backend.src.schemas import AnalysisRequest, AnalysisResponse, CandidateReference, ClarifyRequest, PreviewResponse
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


class UnknownRun(LookupError):
    """The analysis run is unknown or its result has not been saved yet."""


class ClarificationConflict(ValueError):
    """The submitted answer does not match the run's current deterministic clarification."""


class ClarificationUnmapped(ValueError):
    """The free-text answer did not match any option of the current question."""


class PipelineService:
    def __init__(self, settings, client_factory=ce.ClassifierClient,
                 embedding_client_factory=MeowEmbedClient, *, store, llm_factory=RouterClient):
        from backend.src.retrieval import EmbeddingRetriever

        self.settings = settings
        self.client_factory = client_factory
        self.model_lock = Lock()
        self.store = store
        self.llm = llm_factory(settings.llm_base_url, settings.llm_api_key, settings.llm_model,
                               settings.llm_timeout_seconds)
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
            saved_result = result.model_dump(mode="json", exclude_defaults=True)
            details = dict(
                mode="live", run_id=run_id, import_sha256=plan.retrieval.import_sha256,
                planned_requests=len(requests), planned_questions=plan.question_count,
                successful_requests=sum("response" in record for record in records), analysis=report.snapshot(),
            )
            # The saved result stays the untouched primary analysis; clarification state lives in run_artifacts.
            self.store.finish_run(run_id, details, saved_result, failure)
            finalized = True
            logger.info("Analysis saved: run_id=%s status=%s complete_inference=%s elapsed=%.3fs storage=postgresql",
                        run_id, result.status, result.complete_inference, perf_counter() - started)
            if failure:
                raise InferenceFailure(failure, result)
            return with_primary_clarification(saved_result)
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

    def _interpret(self, question: dict, text: str) -> str:
        """A free-text answer becomes a catalog option id through the router; never narrows on its own."""
        try:
            return self.llm.map_option(question["question"], question["options"], text)
        except LLMMappingError as error:
            raise ClarificationUnmapped(str(error)) from error

    def _position(self, run, code: str):
        """The catalogue position of a narrowed candidate, from this run's catalogue import."""
        positions = {position.code: position for position in
                     self.store.get_positions(run.get("catalogue_import_sha256"), [code])}
        position = positions.get(code)
        if position is None:
            raise ClarificationConflict("The selected candidate is missing from the run's catalogue import")
        return position

    @staticmethod
    def _answered_codes(confirmed: list[dict], skipped: list[str]) -> set:
        """Required characteristics that are either confirmed or explicitly skipped."""
        return {record.get("characteristic_code") for record in confirmed} | set(skipped)

    def clarify(self, request: ClarifyRequest) -> AnalysisResponse:
        """Advance the deterministic clarification; pure database work, never the model lock."""
        run = self.store.get_run(request.run_id)
        if run is None or run["result"] is None:
            raise UnknownRun("Run is unknown or its result is not saved yet")
        result = run["result"]
        # Legacy artifacts predate fill_code/confirmed; the defaults keep them readable.
        state = self.store.get_artifact(request.run_id, CLARIFICATION_STATE) or {
            "round": 1, "candidate_codes": initial_candidate_codes(result), "question_id": None, "answers": []}
        confirmed = [dict(record) for record in (state.get("confirmed") or [])]
        skipped = list(state.get("skipped") or [])
        fill_code = state.get("fill_code")
        if fill_code is None:
            current = build_clarification(result, state["candidate_codes"], state["round"])
        else:
            # Fill phase: required-characteristic questions never narrow the codes and never
            # count against the three clarification rounds.
            position = self._position(run, fill_code)
            current = next_required_question(fill_code, position,
                                             self._answered_codes(confirmed, skipped))
        if current is None or request.question_id != current["question_id"]:
            raise ClarificationConflict("The question does not match the run's current clarification state")
        option_id, free_text = request.option_id, None
        if request.text is not None:
            option_id = self._interpret(current, request.text)
            free_text = request.text
        answer = {"question_id": request.question_id, "option_id": option_id}
        if free_text is not None:
            answer["text"] = free_text
        answers = [*(state.get("answers") or []), answer]
        if fill_code is not None:
            return self._answer_required(result, request.run_id, state, current, position, option_id,
                                         answers, confirmed, skipped)
        try:
            narrowed = apply_option(current, option_id, state["candidate_codes"])
        except ValueError as error:
            raise ClarificationConflict(str(error)) from error
        if not narrowed:
            state = {"round": state["round"], "candidate_codes": [], "question_id": request.question_id,
                     "answers": answers}
            self.store.save_artifact(request.run_id, CLARIFICATION_STATE, state)
            return clarification_response(result, suggest_expand=True)
        if len(narrowed) == 1:
            position = self._position(run, narrowed[0])
            following = next_required_question(narrowed[0], position,
                                               self._answered_codes(confirmed, skipped))
            if following is not None:
                state = {"round": state["round"], "candidate_codes": narrowed,
                         "question_id": following["question_id"], "answers": answers,
                         "fill_code": narrowed[0], "confirmed": confirmed, "skipped": skipped}
                self.store.save_artifact(request.run_id, CLARIFICATION_STATE, state)
                return clarification_response(result, clarification=following)
            state = {"round": state["round"], "candidate_codes": narrowed, "question_id": request.question_id,
                     "answers": answers}
            self.store.save_artifact(request.run_id, CLARIFICATION_STATE, state)
            return clarification_response(result, final_card=build_final_card(position, answers, confirmed))
        following_round = state["round"] + 1
        following = build_clarification(result, narrowed, following_round)
        state = {"round": following_round, "candidate_codes": narrowed, "question_id": following["question_id"],
                 "answers": answers}
        self.store.save_artifact(request.run_id, CLARIFICATION_STATE, state)
        return clarification_response(result, clarification=following, manual_choice=following["manual_choice"])

    def _answer_required(self, result, run_id, state, current, position, option_id, answers,
                         confirmed, skipped):
        """Record a required-characteristic answer (or its skip) and move to the next question or the card."""
        selected = next((option for option in current["options"] if option.get("id") == option_id), None)
        if selected is None:
            raise ClarificationConflict("unknown or empty clarification option")
        characteristic = next(item for item in position.characteristics
                              if item.code == current["characteristic_code"])
        if selected.get("candidate_codes"):
            # An empty candidate_codes list marks the skip option: no confirmed record is written.
            confirmed.append({"characteristic_code": characteristic.code, "name": characteristic.name,
                              "value": selected["text"]})
        else:
            skipped.append(characteristic.code)
        following = next_required_question(state["fill_code"], position,
                                           self._answered_codes(confirmed, skipped))
        state = {"round": state["round"], "candidate_codes": state["candidate_codes"],
                 "question_id": current["question_id"] if following is None else following["question_id"],
                 "answers": answers, "fill_code": state["fill_code"], "confirmed": confirmed,
                 "skipped": skipped}
        self.store.save_artifact(run_id, CLARIFICATION_STATE, state)
        if following is None:
            return clarification_response(result, final_card=build_final_card(position, answers, confirmed))
        return clarification_response(result, clarification=following)
