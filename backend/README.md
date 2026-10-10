The backend exposes the existing description → explained КТРУ candidates pipeline over HTTP. It calls the Python code in `experiments/`; it does not load model weights or start Nimble. The meaning of the analysis remains the same: candidates are provisional, missing properties stay visible, and `final_code` is always `null`.

Start from the repository root:

```bash
uv sync --locked
uv run --locked -m backend.src
```

Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) to try requests. The OpenAPI schema is at `/openapi.json`.

The service follows the simple layout used in `../monorepo`:

```text
backend/
  src/
    __init__.py   Source package
    __main__.py   Uvicorn launcher; accepts its command-line options
    app.py        Application assembly, startup and HTTP error handlers
    routes.py     Typed API routes and the service dependency
    schemas.py    Request validation and response contracts
    service.py    Pipeline execution, model access and saved evidence
    settings.py   Environment configuration
  tests/        Offline API integration checks
  README.md     Setup and API usage
```

For development, use `uv run --locked -m backend.src --reload`. To run Uvicorn directly, its application import is `backend.src.app:app`. The launcher defaults to localhost, port 8000 and one worker.

The backend listens on port **8000**. The existing Nimble service or SSH tunnel listens on **8769** by default. Keep the model connection described in [the experiments README](../experiments/README.md) running for live analysis. Preview and backend health work without it.

| Endpoint | What it does |
|---|---|
| `GET /health` | Checks that the backend and catalog are loaded. Reports counts and whether a model request is running; does not contact Nimble. |
| `GET /health/model` | Checks Nimble connectivity and expected model identity, with a timeout of at most five seconds. |
| `POST /preview` | Builds the shortlist, parses measurements, and reports how many model requests and questions would be needed. Makes no model calls and saves no files. |
| `POST /analyze` | Runs the plan, checks constraints, returns the explanation, and saves its evidence. |

Try a preview:

```bash
curl -sS http://127.0.0.1:8000/preview \
  -H 'Content-Type: application/json' \
  --data '{"text":"Нужна аккумуляторная дрель 18 В с реверсом, без ударного режима.","scope":"drills"}'
```

Run the same description through the model:

```bash
curl -sS http://127.0.0.1:8000/analyze \
  -H 'Content-Type: application/json' \
  --data '{"text":"Нужна аккумуляторная дрель 18 В с реверсом, без ударного режима.","scope":"drills"}'
```

Both POST endpoints accept the same body:

```json
{
  "text": "Нужна аккумуляторная дрель 18 В с реверсом, без ударного режима.",
  "scope": "drills",
  "top_k": 8,
  "chunk_size": 4,
  "threshold": 0.8,
  "extras": [{"name": "Цвет", "value": "Синий"}]
}
```

Only `text` is required. `scope` defaults to `all` and can also be `drills`, `tools`, `clothing` or `furniture`. “All” means the experiment's selected catalog snapshot. `top_k` is the shortlist size, from 1 to 32. `chunk_size` puts 1 to 8 categorical questions into each model request. `threshold` is between 0 and 1; it is an uncalibrated acceptance threshold, not a proven correctness probability. `extras` preserves fields supplied by the caller; it does not automatically approve adding them to a specification. Input text is limited to 10,000 characters and retains its original offsets for numeric evidence.

Responses have this structure:

```text
mode                    preview or live
run_id                  null for preview; identifier of saved live evidence
catalog_sha256          identity of the catalog used for this request
planned_requests        number of calls to Nimble's scoring endpoint
planned_questions       total questions across those calls
successful_requests     scoring calls with validated answers
analysis                the complete explanation report
```

Inside `analysis`, `candidates` contains each position's code/version, compatibility, matching and conflicting facts, numeric checks, missing required properties and extra-field actions. `categorical_facts` preserves model classifications and distributions. `numeric_bindings` contains accepted links from input numbers to properties; `unbound_measurements` contains numbers that were not bound. `clarifying_question` is the next question suggested by the pipeline. `limits` explains the checks that remain incomplete.

A preview with a nonempty shortlist has `complete_inference=false` and `status="incomplete_inference"`: the questions are planned but unanswered. A live result can still have `status="needs_clarification"`, even with every model request completed. A `provisional_candidate` does not imply that all required properties or eligibility rules have been checked. See [the ground-up explanation](../experiments/README.md) for the reasoning behind these distinctions.

| HTTP status | Meaning |
|---|---|
| `200` | Processing succeeded. Inspect `analysis.status`; a retrieval miss or incompatible shortlist is also a valid result. |
| `422` | Invalid input or a plan exceeding the server's question budget. No inference is submitted. |
| `502` | Nimble is unavailable, returns invalid answers, or fails during inference. For `/analyze`, `detail.result` contains the partial report and its `run_id`. |
| `503` | A model request is already running. Health and preview remain available. |

Scoring calls run sequentially. The first failure stops the remaining calls; there are no automatic retries. A timed-out request may still be running upstream, so check Nimble before submitting another analysis. The lock prevents overlap within this backend process and is released when the HTTP operation ends; it cannot cancel or track an upstream request after a timeout. Other clients of the shared model also remain outside its control. Use **one Uvicorn worker**; locks are not shared between workers or separate deployments.

An analysis request waits until its run finishes. It may take several minutes because the timeout applies separately to each upstream call. This API does not introduce a background job queue. Synchronous routes execute in FastAPI's thread pool, leaving the backend's health endpoint available while inference waits.

Live evidence is stored in `backend/results/<run_id>/`. `analysis.json` contains the same response envelope returned by the API, and `request_plan.json` contains the planned questions. Model-backed runs also save `health.json`, `manifest.json`, `requests.jsonl` and `summary.json`; a failed initial model health check instead saves `startup_error.json`. A retrieval miss saves the analysis and empty plan without contacting Nimble. These files include submitted descriptions and are ignored by Git.

The catalog loads once during [FastAPI's application lifespan](https://fastapi.tiangolo.com/advanced/events/), rather than for every request. Restart the backend after changing it. By default the server uses `experiments/results/nimble_catalog.json`; if that file is absent, it imports the supplied XML using the existing importer. An unreadable cache or invalid JSON fails startup rather than silently changing snapshots.

Server configuration comes from environment variables, not HTTP input:

| Variable | Default |
|---|---|
| `NIMBLE_BASE_URL` | `http://127.0.0.1:8769` |
| `NIMBLE_TIMEOUT_SECONDS` | `180`, per upstream request |
| `KTRU_CATALOG_PATH` | `experiments/results/nimble_catalog.json` |
| `BACKEND_RESULTS_DIR` | `backend/results` |
| `BACKEND_MAX_QUESTIONS` | `128` |

Relative paths are resolved from the repository root. For example:

```bash
NIMBLE_BASE_URL=http://127.0.0.1:8769 NIMBLE_TIMEOUT_SECONDS=240 \
  uv run --locked -m backend.src
```

Run the offline API checks and the original pipeline regressions:

```bash
uv run --locked python -m unittest discover -s backend/tests -v
uv run --locked python -m unittest discover -s experiments -p 'test_nimble*.py' -v
```

The API checks use a fake model and a small catalog to verify request validation, numeric normalization, preserved missing fields, saved evidence, partial failures and concurrent-run rejection. They do not measure live Nimble prediction quality.
