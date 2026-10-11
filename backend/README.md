The backend turns a product description into explained КТРУ candidates. Initial retrieval embeds the description and catalog product names through meow-embed, then ranks names by cosine similarity. Python checks catalog rules; the existing classifier service scores product identity and characteristic facts. The HTTP result contains readable properties, candidate decisions and the next question. Catalogs, embeddings, analysis history and model evidence are persisted in PostgreSQL with pgvector.

Start from the repository root:

```bash
cp .example.env .env  # First setup only; edit .env for your services.
uv sync --locked
docker compose up -d --wait postgres
uv run --locked python -m scripts.load_db --ktru-only --activate ktru
uv run --locked python -m scripts.embed_db --batch-size 16384
uv run --locked -m backend.src
```

Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) to try requests. The OpenAPI schema is at `/openapi.json`. For development, add `--reload`. The direct Uvicorn application import is `backend.src.app:app`.

For browsers and Swagger, use `POST /analyses` with the usual analysis body. It returns `202` and a `run_id` without waiting for retrieval or inference. Poll `GET /analyses/{run_id}` every two seconds until `status` becomes `completed` or `failed`. The response includes the saved `result` and any `error`; a failed run may include a partial result. The frontend uses this flow automatically and retries transient polling failures without submitting duplicate work. Polling can be resumed after a disconnect using the same ID, including through Swagger. `GET /results/{run_id}` still reads saved results, and `POST /analyze` still supports synchronous clients.

The nginx logs for the reported failures show `499` (the client closed its connection), including a request disconnected about 36 seconds after submission while retrieval and subsequent model batches continued. Increasing nginx or Uvicorn keep-alive settings cannot control a timeout imposed by the browser or an intermediary. Submit-and-poll removes the long idle request that triggers this failure; it does not cancel model work when a polling connection closes.

Compose waits for a healthy backend before starting the frontend. nginx resolves upstream service names through Docker DNS every ten seconds, so recreating a backend container does not leave the proxy using its old IP address. Such stale addresses caused separate `502` responses after rebuilding the stack.

Rebuild the Compose images to apply changes; restarting existing containers does not copy edited source into them:

```bash
docker compose up -d --build backend frontend
```

Background analysis runs inside the single backend process. Restarting it interrupts unfinished runs; this is not a durable job queue. Completed results remain in PostgreSQL. Wait for `/health` to report `model_busy=false` before restarting during active inference.

Submission reserves a run ID in memory and schedules persistence in the worker. The last 32 job statuses are cached, keeping active polling responsive even when PostgreSQL is slow. Older IDs are read from PostgreSQL. If the database cannot save the initial run, polling reports a failed job for the lifetime of the backend process; that unsaved ID will not survive a restart.

The backend and experiment scripts load the repository-root `.env` through `python-dotenv`, regardless of the working directory. `.env` is ignored by Git; [.example.env](../.example.env) is the shared template with localhost addresses. Set `EMBEDDING_BASE_URL` and `CLASSIFIER_BASE_URL` in `.env` to your actual services. Exported environment variables take precedence; CLI flags override configuration for that invocation. Restart after editing configuration. Missing required variables fail with a setup message rather than silently choosing a service.

The template listens on **8000** and uses `google/embeddinggemma-2` for embeddings. PostgreSQL is required: startup opens the connection pool, applies versioned SQL migrations and logs the database connection result. The Compose service publishes PostgreSQL on `127.0.0.1:${POSTGRES_PORT}` and persists it in the `postgres_data` Docker volume. Credentials and `DATABASE_URL` come from `.env`; `python-dotenv` expands the URL's `${POSTGRES_*}` references. Restarting containers preserves the database.

The classifier's `/health` and meow-embed's `/models` are checked concurrently at every startup. These checks validate model IDs without inference or embedding. Results appear in the server log and the `connection_checks` table, with UTC timestamps, endpoints, elapsed times and model details or errors. Checks use `STARTUP_CHECK_TIMEOUT_SECONDS`, capped by each service's timeout. Failed upstream checks are logged and allow startup; a database connection or migration failure prevents startup. `/preview` needs the embedder; `/analyze` also needs the classifier.

Import a relational XML snapshot with `scripts.load_db` and activate it under `KTRU_CATALOG_KEY` (`ktru` in the template). Backend startup does not import a catalogue or build catalogue embeddings. `backend.src.migrate` applies schema migrations only; the standalone experiment JSON cache is not used by relational retrieval.

### Backfill catalogue embeddings

With PostgreSQL running and `EMBEDDING_BASE_URL` pointing to an embed service that provides the configured 768-dimensional model, run from the repository root:

```bash
uv run --locked python -m scripts.embed_db
# Optional overrides:
uv run --locked python -m scripts.embed_db --catalog-key ktru --batch-size 32
```

The job pins the active import at startup and fills PostgreSQL `embedding` and `embedding_config` columns. Product documents contain the position name; characteristic documents contain the product and characteristic names on separate lines; qualitative value documents add the value text. Only actual characteristics and qualitative values without parsing issues are included. Numeric ranges are not embedded. All position names in the snapshot are processed, including positions not currently eligible for retrieval.

Each batch commits separately, so rerun the same command after a failure or interruption to resume. Matching embeddings are skipped; embeddings from a different model/prompt/format fingerprint are replaced. Identical documents within a batch share one embedding request entry. `EMBEDDING_BATCH_SIZE` defaults to 32 in the template; `--batch-size` overrides the number of database rows processed per batch. Catalogue text is sent to `EMBEDDING_BASE_URL`; the job does not contact the classifier. Completed vectors survive restarts.

The backend uses lexical retrieval until a matching position embedding exists, then combines lexical and semantic field-level results with rank fusion and name diversification. Readiness is not a full-coverage check: semantic search can become available while the backfill is still running. Changing `EMBEDDING_MODEL` or the prompts requires running the backfill again. Similarity scores rank candidates; they are not acceptance probabilities or proof of final eligibility.

The client uses meow-embed's [`POST /embed` API](https://github.com/dantetemplar/meow-embed), decodes base64 float32 vectors, validates model identity and dimensions, and normalizes vectors for cosine search. It sends explicit query/document prefixes from [EmbeddingGemma 2's configuration](https://huggingface.co/google/embeddinggemma-2/blob/main/config_sentence_transformers.json).

Embedding logs use the server logger. At `LOG_LEVEL=info`, they show the model, endpoint, text counts, timeout, request duration and returned dimensions; index build/batch progress, cache loading or reuse; search scope, candidate count and query/total timing. Cache corruption and request failures produce warnings. Set `LOG_LEVEL=debug` to include complete outgoing embedding payloads. Each saved analysis report in `analysis_runs.analysis` also records the index source (`built`, `postgresql` or `memory`), name count, dimensions and embedding search timings under `analysis.retrieval`. Outgoing online embedding payloads, dimensions, timings and failures are also retained in `embedding_calls`; analysis calls carry their run ID. The backfill logs batch progress but does not persist request evidence. Startup's `/models` check does not build vectors; use `scripts.embed_db` to prepare them.

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
    startup.py      Upstream connection checks and startup logs
    storage.py      Connection pool and transactional PostgreSQL persistence
    migrate.py      Schema migration and legacy file import command
  migrations/       Versioned SQL schema
  tests/            Offline API checks and opt-in PostgreSQL integration tests
```

`experiments/embedding_retrieval.py` contains the shared HTTP client, cache and semantic retrieval implementation.

| Endpoint | Response |
|---|---|
| `GET /health` | `{"status":"ok","model_busy":false}`. Checks backend startup; does not probe the classifier. |
| `GET /health/model` | `{"status":"ok","model":"jiwo-4b"}`. Probes the classifier using `CLASSIFIER_HEALTH_TIMEOUT_SECONDS` and validates model identity. |
| `POST /preview` | Retrieval shortlist, planned classifier request/question counts and candidate code, version and name. Uses prepared catalogue embeddings when available; performs no classifier calls or analysis-run writes. |
| `POST /analyze` | Provisional recommendation, interpreted properties, explained candidates, missing fields and next question. Saves evidence. |
| `GET /results/{run_id}` | Read an already saved response without contacting either model. Use the run ID from server logs after a lost browser response. Returns `404` if unknown or still processing. |

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

`scope` defaults to `all`, meaning the experiment's selected snapshot, not every КТРУ record. Other scopes are `drills`, `tools`, `clothing` and `furniture`. `top_k` is 1–32; `chunk_size` is 1–8 questions per logical categorical group, capped by the classifier batch size when batching is enabled. `threshold` is an uncalibrated acceptance threshold between 0 and 1. `extras` accepts caller-supplied `{ "name": "Цвет", "value": "Синий" }` fields. It does not automatically approve adding them to a specification. Text is limited to 10,000 characters.

Retrieval reserves slots for eligible siblings of higher-ranked catalogue families before taking lower-ranked hits, when the complete family fits within `top_k`. This keeps characteristic variants available even when semantic ranking prefers a conflicting sibling. Families too large to fit still retain their complete splitting domains for analysis. Extraction checks catalogue properties; descriptions of additional properties absent from the catalogue, such as an adjustable wrench's non-slip handle, must be supplied through `extras` for an explicit additional-characteristic policy decision.

`BACKEND_MAX_QUESTIONS` is a hard cap on submitted classifier questions, rather than a reason to reject a large shortlist. When a plan exceeds it, the backend removes candidates from the end of the retrieved order until the full checks fit. `top_k` is therefore an upper bound. Family splitting domains remain intact for retained parents, including siblings outside the shortened shortlist; reducing the shortlist cannot by itself resolve a family. Preview and analysis use the same budget adjustment without repeating embedding retrieval.

If even the first candidate exceeds the budget, the backend keeps it and submits a bounded partial plan, prioritizing product identity and measurements explicitly supplied in the description. The response is HTTP `200` with `status=incomplete_inference`, `complete_inference=false` and no recommendation. Skipped characteristic checks remain unknown. Warnings explain reduced coverage in both endpoints. Saved retrieval metadata records the original and retained candidate/question counts under `question_budget`; saved plans also retain `skipped_question_ids`. Increase `BACKEND_MAX_QUESTIONS` and restart if complete checks for that candidate are needed.

`CLASSIFIER_BATCH_SIZE=16` in `.env` packs independent product, categorical and numeric questions with the same description/model into HTTP requests of up to 16 questions. Values 1–64 select a limit; 0 disables packing for comparison or older services. `/preview`, saved plans and request counters report the actual HTTP batches; the total question budget is unchanged. Question IDs are namespaced to avoid collisions between numeric checks, then mapped back for analysis. Each complete outgoing batch is committed to `model_calls` before dispatch; saved records include the original jobs and ID mapping. Earlier successful batches remain available if a later batch fails. The HTTP batches are sent sequentially.

The deployment files under `data/jiwo-deployment` identify the standard jiwo server at revision `8716ababb0924bccadeed3fe1f489d371c554145`, with an FP16 wrapper for V100. That revision already batches questions on the GPU; no server API change is required. GPU batch memory is controlled separately by the server's `JIWO_BATCH_TOKENS`. Its logs report reference-kernel fallbacks for convolution and linear attention, which remain a separate performance consideration.

The live batching check on 2026-10-10 processed the drill example's 61 questions as four requests (16/16/16/13), compared with 19 previously. Classifier time was 7.56 seconds versus 16.05 seconds in the earlier run; all 61 selected answers matched, with a maximum probability difference of 0.00124. The test reused a saved embedding shortlist because the live embedder timed out. Its 8.32-second API duration excludes live retrieval, and the comparison is one observed example rather than a controlled latency benchmark. Request counts, full batch evidence, mapping back to every original check, and saved-result recovery were verified in PostgreSQL.

```bash
curl -sS http://127.0.0.1:8000/analyze \
  -H 'Content-Type: application/json' \
  --data '{"text":"Нужна аккумуляторная дрель 18 В с реверсом, без ударного режима"}'
```

To inspect the plan without calling the classifier, change `/analyze` to `/preview`. Preview candidates are semantic search results, not confirmed matches. Its response has `planned_requests`, `planned_questions` and `candidates`, plus `warnings` when the question budget reduces coverage. The first preview also warms the catalog vector cache.

Read an analysis in this order:

1. **`status`** tells you whether more input or a review is needed.
2. **`recommended_candidate`** identifies a provisional candidate as `code@version`, or is `null` when evidence is insufficient. It is not a final validated code.
3. **`properties`** lists accepted description facts and normalized measurements, such as battery power and `18 В`. Unstated optional properties are omitted. Ambiguous accepted values are withheld and explained in warnings.
4. **`candidates`** is ordered by `probabilities.supported` descending, with ties broken by code and version. `choice` and `probabilities` expose the classifier's product identity answer across `supported`, `contradicted`, `unknown` and `conflicting`. These scores are uncalibrated and do not measure overall catalogue compatibility: characteristic checks still determine `status`. Candidates with no model answer appear last and omit these fields; older saved results can also omit them. Every decision has readable `reasons`.
5. **`missing_required`** lists outstanding catalog-required properties for compatible candidates. Uncertain and rejected alternatives omit this input checklist; their decisions and reasons remain visible. **`clarifying_question`** asks for the next useful detail.

| Candidate `status` | Meaning |
|---|---|
| `compatible` | Product identity is supported above the threshold; performed characteristic checks found no conflict or unresolved candidate rule. Missing required fields may still exist. |
| `uncertain` | The candidate is not established as a match, but the evidence is insufficient to exclude it. |
| `rejected` | An accepted value conflicts with its rules, a number is outside permitted values, or its product identity is confidently contradicted. |

Optional empty candidate lists are omitted. `unmatched_properties` names interpreted properties absent from the candidate's schema; absence is not automatically a contradiction. `extra_characteristics` preserves caller-supplied fields and their actions: map and validate, do not add, review before adding, or policy unknown.

Several candidates can be `compatible` at once; this produces `needs_clarification` without a recommendation. `compatible` means the checks performed passed, not that all required specifications are present or a final code has been validated. Model answers still use `supported` for individual facts and product identity. Older saved candidate statuses named `supported` are returned as `compatible` by `GET /results/{run_id}` without rewriting stored evidence.

Your saved drill example exposed two mechanical-drill alternatives whose rejection score was 0.749, below the 0.8 threshold. They now remain explicitly **uncertain**. The mains drill is **rejected** because it does not permit battery power. The battery drill is **compatible**, becomes the provisional recommendation, and its missing requirements drive the next question. The system does not lower the threshold or pretend the mechanical alternatives have been conclusively excluded.

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
| `ready_for_review` | Required fields of the compatible candidate are covered; review applicability and evidence. No final code is issued. |
| `incomplete_inference` | Some scoring calls failed, are missing, or were skipped to stay within the question budget. Do not interpret absent answers as negative facts. |
| `retrieval_miss` | The selected scope contains no candidates; review the catalog and scope. A nonempty semantic index returns nearest candidates even for unrelated input. |
| `no_compatible_shortlist_candidate` | Review reported contradictions and search coverage. |

`complete_inference` means all planned scoring calls returned validated answers and no checks were skipped for retained candidates or families; it does not measure their accuracy. Removing candidates to fit the budget still allows complete inference for the retained shortlist. `requires_review` is always `true`: catalog coverage, lifecycle/applicability and categorical text evidence are still experimental. `warnings` exposes unresolved alternatives, conflicting values, truncated retrieval, budget adjustments and numbers that could not be bound. `clarifying_question` is `null` when no further input question is needed, but review can still remain.

| HTTP status | Meaning |
|---|---|
| `200` | Processing succeeded; inspect the analysis status. |
| `422` | Invalid input or unsupported plan data. No classifier calls are submitted; embedding retrieval may already have run. Oversized question plans are adjusted automatically. |
| `502` | Embedding retrieval or classifier failed. Embedding failures return `detail.result=null`; the failed run and error remain in PostgreSQL. Classifier failures return the compact partial result under `detail.result`, including its `run_id`. |
| `503` | A model operation is already running, or the database is unavailable. |

Scoring calls run sequentially and stop at the first failure, without automatic retries. A timed-out upstream request may still be running; check the classifier before resubmitting. The lock only covers this process and cannot cancel or track remote work after timeout. Use **one Uvicorn worker**. Synchronous `/analyze` waits for completion and can take several minutes; the timeout applies separately to each upstream call. `/analyses` returns immediately and performs the same work in a background task.

If Swagger displays `TypeError: NetworkError when attempting to fetch resource`, the browser did not obtain a usable response. This message alone does not identify the cause. An ordinary HTTP `502` or `503` is a readable response rather than a rejected Fetch promise; see [MDN's Fetch documentation](https://developer.mozilla.org/en-US/docs/Web/API/Window/fetch). Network/proxy interruptions, browser blocking, or server reloads can interrupt delivery. A timeout is one possibility, not an established diagnosis.

`/analyze` runs in a worker thread and can continue after the browser disconnects, saving its result normally. This implementation does not cancel inference on disconnect. Avoid immediately resubmitting: inspect `/health` for `model_busy`, and look for `Analysis started: run_id=...` and `Analysis saved: run_id=...` in the server log. Retrieve a completed result in Swagger through `GET /results/{run_id}`, or inspect `analysis_runs.result` in PostgreSQL. A recovered partial result still has `complete_inference=false`; retrieval itself returns `200` because reading the saved database result succeeded.

To diagnose a recurring browser failure, open Developer Tools → Network before submitting and inspect the failing request's URL, elapsed time, status and browser Console error. Use Swagger served by the same backend (`/docs`) and confirm its request uses the same scheme, host and port. Test without `--reload` while diagnosing interruptions. If using a reverse proxy, inspect its request/read timeout and logs; `CLASSIFIER_TIMEOUT_SECONDS` does not control the browser-to-backend connection. Increasing Uvicorn's keep-alive timeout does not extend an active request: it applies between requests, as shown in [Uvicorn's HTTP implementation](https://github.com/encode/uvicorn/blob/master/uvicorn/protocols/http/h11_impl.py). Use `/analyses` and poll its run ID to avoid holding one HTTP connection open for the complete analysis.

Backend evidence is stored in these tables:

| Table | Contents |
|---|---|
| `catalog_snapshots`, `catalog_sources` | Versioned catalog payloads, hashes and configured catalog pointers. |
| `catalog_positions`, `catalog_facts` | Searchable product positions and characteristic facts, linked to snapshots. |
| `embedding_indexes`, `catalog_embeddings` | Model/prompt/name fingerprints, dimensions and pgvector vectors. |
| `analysis_runs` | Original API input, plan, counts, status, errors, detailed analysis and compact response. |
| `model_calls` | Exact outgoing JSON payloads, IDs, URLs, timestamps, raw responses, errors and timings. The outgoing request is committed before dispatch. JSON preserves criterion order. |
| `run_artifacts` | Health, manifest, summary and startup failures; legacy JSON artifacts retain their original names. |
| `embedding_calls` | Outgoing embedding requests, model, URL, associated run, dimensions, durations and errors. |
| `connection_checks` | Startup connectivity results, including failed checks. |
| `backend_schema_migrations` | Applied migration versions and checksums; modifying an applied migration fails startup. |

At `LOG_LEVEL=info`, classifier requests produce one concise line with request progress, run ID, request ID, experiment and question count. Set `LOG_LEVEL=debug` to include the complete outgoing JSON, including timestamps, destination URL, input text, instructions and criteria. Full requests remain persisted in `model_calls` at every log level. Standalone experiment runs apply the same console levels and continue saving full payloads to `model_requests.jsonl`.

A retrieval miss saves the response, detailed report and empty plan without contacting the classifier. Interrupted model calls retain their outgoing payload and `running` status when no response was saved. Requests and answers are committed separately so in-flight evidence is visible to other database readers. Catalog provenance is retained for every new run. Submitted descriptions are stored in the database.

Inspect recent runs or model requests with the container's SQL client:

```bash
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

```sql
SELECT id, status, planned_requests, error FROM analysis_runs ORDER BY created_at DESC LIMIT 10;
SELECT ordinal, status, url, request, response, error
FROM model_calls WHERE run_id = '<run_id>' ORDER BY ordinal;
SELECT checked_at, service, payload FROM connection_checks ORDER BY checked_at DESC LIMIT 10;
```

| Environment variable | Value in `.example.env` |
|---|---|
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Compose database credentials; template uses local development values |
| `POSTGRES_PORT` | `5432`, bound to localhost |
| `DATABASE_URL` | Expanded PostgreSQL connection URL |
| `DATABASE_CONNECT_TIMEOUT_SECONDS` | `5` |
| `DATABASE_POOL_MIN_SIZE`, `DATABASE_POOL_MAX_SIZE` | `1`, `4` |
| `DATABASE_POOL_TIMEOUT_SECONDS` | `10`, waiting for a pool connection |
| `KTRU_CATALOG_KEY` | `ktru`, database catalog pointer |
| `CLASSIFIER_BASE_URL` | `http://127.0.0.1:8769` |
| `CLASSIFIER_MODEL` | `jiwo-4b` |
| `CLASSIFIER_TIMEOUT_SECONDS` | `180`, per upstream request |
| `CLASSIFIER_HEALTH_TIMEOUT_SECONDS` | `5`, maximum health-probe timeout |
| `KTRU_CATALOG_PATH` | `experiments/results/catalog.json`, initial bootstrap/legacy import source |
| `KTRU_XML_DIR` | `data`, importer source when the catalog cache is absent |
| `EXPERIMENT_RESULTS_DIR` | `experiments/results`, standalone CLI evidence |
| `BACKEND_RESULTS_DIR` | `backend/results`, legacy run import source |
| `BACKEND_STARTUP_LOG_PATH` | `backend/results/startup_connections.jsonl`, legacy startup log import source |
| `STARTUP_CHECK_TIMEOUT_SECONDS` | `5`, maximum timeout per startup probe |
| `BACKEND_MAX_QUESTIONS` | `128`, hard question cap with automatic shortlist reduction and partial-check fallback |
| `EMBEDDING_BASE_URL` | `http://127.0.0.1:8067` |
| `EMBEDDING_MODEL` | `google/embeddinggemma-2` |
| `EMBEDDING_TIMEOUT_SECONDS` | `60`, per embedding request |
| `EMBEDDING_BATCH_SIZE` | `32` catalog names per request |
| `EMBEDDING_MAX_NAMES` | `4` distinct names per shortlist, interleaving code/version alternatives |
| `EMBEDDING_CACHE_PATH` | `backend/cache/catalog_embeddings.json`, standalone CLI cache/legacy import source |
| `EMBEDDING_QUERY_PROMPT`, `EMBEDDING_DOCUMENT_PROMPT` | Model prefixes; preserve the quoted trailing spaces |
| `BACKEND_HOST`, `BACKEND_PORT` | `127.0.0.1`, `8000` |
| `LOG_LEVEL` | `info`; use `debug` for full embedding payloads |
| `PIPELINE_TOP_K`, `PIPELINE_CHUNK_SIZE`, `PIPELINE_THRESHOLD` | Request defaults: `8`, `4`, `0.8` |

Relative paths resolve from the repository root. Run the offline API and pipeline regressions with:

```bash
uv run --locked python -m unittest discover -s backend/tests -v
uv run --locked python -m unittest backend.tests.test_question_budget -v
uv run --locked python -m unittest discover -s experiments -p 'test_*.py' -v
# Real PostgreSQL checks create and remove isolated test schemas.
RUN_POSTGRES_TESTS=1 uv run --locked python -m unittest discover -s backend/tests -v
```

Tests cover embedding transport, semantic retrieval without shared words, scope filtering, deduplicated vector caching, cache invalidation, service failures, unresolved alternatives, contradictory accepted facts, numeric rule uncertainty, unit conversion, required fields, compact responses, saved evidence and partial failures. They use fake embeddings and a fake classifier; these checks verify the pipeline rather than real-model retrieval or prediction quality.

PostgreSQL integration tests verify migrations, persisted catalogs, pgvector ranking, atomic index replacement, pre-dispatch commits, criterion order, restart recovery, partial failures, embedding request records and idempotent legacy import. They use the database configured in `.env` with isolated schemas.
