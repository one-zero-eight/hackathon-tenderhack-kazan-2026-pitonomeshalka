The backend turns a product description into explained КТРУ candidates. Python finds candidates and checks catalog rules; the existing Nimble service scores the meaning of the description. The HTTP result contains readable properties, candidate decisions and the next question. Full model evidence is saved separately.

Start from the repository root:

```bash
uv sync --locked
uv run --locked -m backend.src
```

Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) to try requests. The OpenAPI schema is at `/openapi.json`. For development, add `--reload`. The direct Uvicorn application import is `backend.src.app:app`.

The backend listens on **8000**; Nimble or its SSH tunnel listens on **8769** by default. Keep the model connection described in [the experiments README](../experiments/README.md) running for live analysis. Health and preview work without it.

```text
backend/
  src/
    __main__.py     Uvicorn launcher
    app.py          Application assembly, startup and HTTP errors
    routes.py       Typed API routes and service injection
    schemas.py      Request validation and compact response contracts
    service.py      Pipeline execution, model access and saved evidence
    presentation.py Readable properties and candidate explanations
    settings.py     Environment configuration
  tests/            Offline API integration checks
  results/          Local run evidence, ignored by Git
```

| Endpoint | Response |
|---|---|
| `GET /health` | `{"status":"ok","model_busy":false}`. Checks backend startup; does not probe Nimble. |
| `GET /health/model` | `{"status":"ok","model":"bespokelabs/Bespoke-Nimble-9B-v3"}`. Probes Nimble with a timeout of at most five seconds and validates model identity. |
| `POST /preview` | Planned request/question counts and candidate code, version and name. No inference or files. |
| `POST /analyze` | Provisional recommendation, interpreted properties, explained candidates, missing fields and next question. Saves evidence. |

Both POST endpoints accept the same body. Only `text` is required:

```json
{
  "text": "Нужна аккумуляторная дрель 18 В с реверсом, без ударного режима",
  "scope": "all",
  "top_k": 8,
  "chunk_size": 4,
  "threshold": 0.8,
  "extras": []
}
```

`scope` defaults to `all`, meaning the experiment's selected snapshot, not every КТРУ record. Other scopes are `drills`, `tools`, `clothing` and `furniture`. `top_k` is 1–32; `chunk_size` is 1–8 questions per categorical scoring call. `threshold` is an uncalibrated acceptance threshold between 0 and 1. `extras` accepts caller-supplied `{ "name": "Цвет", "value": "Синий" }` fields. It does not automatically approve adding them to a specification. Text is limited to 10,000 characters.

```bash
curl -sS http://127.0.0.1:8000/analyze \
  -H 'Content-Type: application/json' \
  --data '{"text":"Нужна аккумуляторная дрель 18 В с реверсом, без ударного режима"}'
```

To inspect the plan without the model, change `/analyze` to `/preview`. Preview candidates are name-search results, not confirmed matches. Its response has only `planned_requests`, `planned_questions` and `candidates`.

Read an analysis in this order:

1. **`status`** tells you whether more input or a review is needed.
2. **`recommended_candidate`** identifies a provisional candidate as `code@version`, or is `null` when evidence is insufficient. It is not a final validated code.
3. **`properties`** lists accepted description facts and normalized measurements, such as battery power and `18 В`. Unstated optional properties are omitted. Ambiguous accepted values are withheld and explained in warnings.
4. **`candidates`** is ordered with supported candidates first, then uncertain alternatives, then rejected candidates. Every decision has readable `reasons`.
5. **`missing_required`** lists outstanding catalog-required properties for supported candidates. Uncertain and rejected alternatives omit this input checklist; their decisions and reasons remain visible. **`clarifying_question`** asks for the next useful detail.

| Candidate `status` | Meaning |
|---|---|
| `supported` | Product identity is supported above the threshold; performed characteristic checks found no conflict or unresolved candidate rule. Missing required fields may still exist. |
| `uncertain` | The candidate is not established as a match, but the evidence is insufficient to exclude it. |
| `rejected` | An accepted value conflicts with its rules, a number is outside permitted values, or its product identity is confidently contradicted. |

Optional empty candidate lists are omitted. `unmatched_properties` names interpreted properties absent from the candidate's schema; absence is not automatically a contradiction. `extra_characteristics` preserves caller-supplied fields and their actions: map and validate, do not add, review before adding, or policy unknown.

Your saved drill example exposed two mechanical-drill alternatives whose rejection score was 0.749, below the 0.8 threshold. They now remain explicitly **uncertain**. The mains drill is **rejected** because it does not permit battery power. The battery drill is **supported**, becomes the provisional recommendation, and its missing requirements drive the next question. The system does not lower the threshold or pretend the mechanical alternatives have been conclusively excluded.

Reprocessing that run produces these important fields:

```json
{
  "status": "needs_clarification",
  "complete_inference": true,
  "recommended_candidate": "28.24.11.000-00000002@4",
  "requires_review": true,
  "properties": [
    {"name": "Наличие режима реверса", "value": "Да"},
    {"name": "Наличие режима ударного сверления", "value": "Нет"},
    {"name": "Напряжение аккумулятора", "value": "18 В"},
    {"name": "Тип питания", "value": "От аккумулятора"}
  ]
}
```

This excerpt omits `run_id`, the candidate list, the next question and warnings. The battery candidate still needs minimum/maximum chuck diameters, maximum RPM and battery capacity. The next question asks for battery capacity and its catalog unit, rather than asking whether the explicitly battery-powered product is mechanical.

| Analysis `status` | What to do |
|---|---|
| `needs_clarification` | Answer the next question and resubmit the updated description. |
| `ready_for_review` | Required fields of the supported candidate are covered; review applicability and evidence. No final code is issued. |
| `incomplete_inference` | Some scoring calls failed or are missing. Do not interpret absent answers as negative facts. |
| `retrieval_miss` | Clarify the product name or broaden retrieval; no name-search candidate was found. |
| `no_compatible_shortlist_candidate` | Review reported contradictions and search coverage. |

`complete_inference` means all planned scoring calls returned validated answers; it does not measure their accuracy. `requires_review` is always `true`: catalog coverage, lifecycle/applicability and categorical text evidence are still experimental. `warnings` exposes unresolved alternatives, conflicting values, truncated retrieval and numbers that could not be bound. `clarifying_question` is `null` when no further input question is needed, but review can still remain.

| HTTP status | Meaning |
|---|---|
| `200` | Processing succeeded; inspect the analysis status. |
| `422` | Invalid input or a plan exceeding the question budget. No inference is submitted. |
| `502` | Nimble is unavailable or inference failed. `/analyze` returns the compact partial result under `detail.result`, including its `run_id`. |
| `503` | A model operation is already running. Health and preview remain available. |

Scoring calls run sequentially and stop at the first failure, without automatic retries. A timed-out upstream request may still be running; check Nimble before resubmitting. The lock only covers this process and cannot cancel or track remote work after timeout. Use **one Uvicorn worker**. Analysis waits for completion and can take several minutes; the timeout applies separately to each upstream call. There is no background queue.

Evidence is saved under `backend/results/<run_id>/`:

| File | Contents |
|---|---|
| `response.json` | The compact response returned by the current API. |
| `analysis.json` | Detailed report, distributions, catalog provenance, measurement offsets, retrieval evidence, question counts and catalog hash. |
| `request_plan.json` | Planned model questions. |
| `model_requests.jsonl` | Exact inference payloads, request IDs, UTC logging timestamps and destination URLs. Each line is flushed before dispatch, including calls that later fail. Payloads are also printed to the server console. |
| `requests.jsonl` | Raw request/answer records, including failures. |
| `health.json`, `manifest.json`, `summary.json` | Model health, run configuration and request statistics. |
| `startup_error.json` | Failure of the initial model health check, when applicable. |

A retrieval miss saves the compact response, detailed report and empty plan without contacting Nimble. Earlier runs keep their original files; the demonstrated saved run additionally has `response_reprocessed.json`, generated offline using its existing answers. Evidence files contain submitted descriptions and are ignored by Git.

The catalog loads once at startup; restart after changing it. The default cache is `experiments/results/nimble_catalog.json`. If absent, the existing importer reads the supplied XML. Invalid JSON or an unreadable cache fails startup.

| Environment variable | Default |
|---|---|
| `NIMBLE_BASE_URL` | `http://127.0.0.1:8769` |
| `NIMBLE_TIMEOUT_SECONDS` | `180`, per upstream request |
| `KTRU_CATALOG_PATH` | `experiments/results/nimble_catalog.json` |
| `BACKEND_RESULTS_DIR` | `backend/results` |
| `BACKEND_MAX_QUESTIONS` | `128` |

Relative paths resolve from the repository root. Run the offline API and pipeline regressions with:

```bash
uv run --locked python -m unittest discover -s backend/tests -v
uv run --locked python -m unittest discover -s experiments -p 'test_nimble*.py' -v
```

Tests cover unresolved alternatives, contradictory accepted facts, numeric rule uncertainty, unit conversion, required fields, compact responses, saved evidence and partial failures. They use a fake model; replaying saved answers tests the revised logic without measuring new model prediction quality.
