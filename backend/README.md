The backend turns a product description into explained КТРУ candidates. Initial retrieval embeds the description and catalog product names through meow-embed, then ranks names by cosine similarity. Python checks catalog rules; the existing classifier service scores product identity and characteristic facts. The HTTP result contains readable properties, candidate decisions and the next question. Catalogs, embeddings, analysis history and model evidence are persisted in PostgreSQL with pgvector.

Start from the repository root:

```bash
cp .example.env .env  # First setup only; edit .env for your services.
uv sync --locked
docker compose up -d --wait postgres
uv run --locked -m backend.src.migrate --import-files  # Import existing files once; safe to repeat.
uv run --locked -m backend.src
```

Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) to try requests. The OpenAPI schema is at `/openapi.json`. For development, add `--reload`. The direct Uvicorn application import is `backend.src.app:app`.

The backend and experiment scripts load the repository-root `.env` through `python-dotenv`, regardless of the working directory. `.env` is ignored by Git; [.example.env](../.example.env) is the shared template with localhost addresses. Set `EMBEDDING_BASE_URL` and `CLASSIFIER_BASE_URL` in `.env` to your actual services. Exported environment variables take precedence; CLI flags override configuration for that invocation. Restart after editing configuration. Missing required variables fail with a setup message rather than silently choosing a service.

The template listens on **8000** and uses `google/embeddinggemma-2` for embeddings. PostgreSQL is required: startup opens the connection pool, applies versioned SQL migrations and logs the database connection result. The Compose service publishes PostgreSQL on `127.0.0.1:${POSTGRES_PORT}` and persists it in the `postgres_data` Docker volume. Credentials and `DATABASE_URL` come from `.env`; `python-dotenv` expands the URL's `${POSTGRES_*}` references. Restarting containers preserves the database.

The classifier's `/health` and meow-embed's `/models` are checked concurrently at every startup. These checks validate model IDs without inference or embedding. Results appear in the server log and the `connection_checks` table, with UTC timestamps, endpoints, elapsed times and model details or errors. Checks use `STARTUP_CHECK_TIMEOUT_SECONDS`, capped by each service's timeout. Failed upstream checks are logged and allow startup; a database connection or migration failure prevents startup. `/preview` needs the embedder; `/analyze` also needs the classifier.

On the first startup with an empty database catalog, the backend imports `KTRU_CATALOG_PATH` if present, otherwise the supplied XML under `KTRU_XML_DIR`. It stores a versioned snapshot and normalized positions/facts under `KTRU_CATALOG_KEY`. Subsequent startups load this catalog from PostgreSQL. Original XML files remain import sources. To replace the catalog, import the new snapshot with `PostgresStore.save_catalog(catalog, key)` and restart the backend.

Catalog vectors are built lazily on the first search, in batches of 32 unique normalized names, then committed atomically to PostgreSQL. The current snapshot has 1,302 entries and 283 unique names. pgvector computes cosine similarity for names in the requested scope; Python preserves the existing code/version diversification. Subsequent searches embed only the incoming description. Cached catalog vectors survive restarts and are also reused in memory. Changes to the name set, embedding model or prompts create a new index fingerprint. To rebuild after changing weights under the same model ID, delete the relevant row from `embedding_indexes` and restart; dependent vectors are removed automatically.

`backend.src.migrate --import-files` imports existing catalog/vector caches, saved backend runs and startup logs without inference or re-embedding. Run imports are transactional and idempotent; existing database runs are skipped. Source files are preserved, but new backend runs use PostgreSQL exclusively. Standalone experiment CLIs retain their file export/cache behavior.

There is no shared-word requirement or automatic lexical fallback. Retrieval takes up to `EMBEDDING_MAX_NAMES` nearest distinct names within the requested scope (four in the template), then interleaves their code/version alternatives up to `top_k`. Similarity scores are rankings, not acceptance probabilities; there is no similarity acceptance cutoff. Even unrelated inputs can get nearest candidates, which the classifier must assess. A semantic shortlist still cannot establish complete catalog coverage or final eligibility.

The client uses meow-embed's [`POST /embed` API](https://github.com/dantetemplar/meow-embed), decodes base64 float32 vectors, validates model identity and dimensions, and normalizes vectors for cosine search. It sends explicit query/document prefixes from [EmbeddingGemma 2's configuration](https://huggingface.co/google/embeddinggemma-2/blob/main/config_sentence_transformers.json).

Embedding logs use the server logger. At `LOG_LEVEL=info`, they show the model, endpoint, text counts, timeout, request duration and returned dimensions; index build/batch progress, cache loading or reuse; search scope, candidate count and query/total timing. Cache corruption and request failures produce warnings. Set `LOG_LEVEL=debug` to include complete outgoing embedding payloads. Each saved analysis report in `analysis_runs.analysis` also records the index source (`built`, `postgresql` or `memory`), name count, dimensions and embedding search timings under `analysis.retrieval`. Outgoing embedding payloads, dimensions, timings and failures are also retained in `embedding_calls`; analysis calls carry their run ID. Startup's `/models` check does not build vectors; the first search does.

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
| `POST /preview` | Embedding shortlist, planned classifier request/question counts and candidate code, version and name. May build the vector cache; performs no classifier calls or analysis-run writes. |
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

`CLASSIFIER_BATCH_SIZE=16` in `.env` packs independent product, categorical and numeric questions with the same description/model into HTTP requests of up to 16 questions. Values 1–64 select a limit; 0 disables packing for comparison or older services. `/preview`, saved plans and request counters report the actual HTTP batches; the total question budget is unchanged. Question IDs are namespaced to avoid collisions between numeric checks, then mapped back for analysis. Each complete outgoing batch is committed to `model_calls` before dispatch; saved records include the original jobs and ID mapping. Earlier successful batches remain available if a later batch fails. The HTTP batches are sent sequentially.

The deployment files under `data/jiwo-deployment` identify the standard jiwo server at revision `8716ababb0924bccadeed3fe1f489d371c554145`, with an FP16 wrapper for V100. That revision already batches questions on the GPU; no server API change is required. GPU batch memory is controlled separately by the server's `JIWO_BATCH_TOKENS`. Its logs report reference-kernel fallbacks for convolution and linear attention, which remain a separate performance consideration.

The live batching check on 2026-10-10 processed the drill example's 61 questions as four requests (16/16/16/13), compared with 19 previously. Classifier time was 7.56 seconds versus 16.05 seconds in the earlier run; all 61 selected answers matched, with a maximum probability difference of 0.00124. The test reused a saved embedding shortlist because the live embedder timed out. Its 8.32-second API duration excludes live retrieval, and the comparison is one observed example rather than a controlled latency benchmark. Request counts, full batch evidence, mapping back to every original check, and saved-result recovery were verified in PostgreSQL.

```bash
curl -sS http://127.0.0.1:8000/analyze \
  -H 'Content-Type: application/json' \
  --data '{"text":"Нужна аккумуляторная дрель 18 В с реверсом, без ударного режима"}'
```

To inspect the plan without calling the classifier, change `/analyze` to `/preview`. Preview candidates are semantic search results, not confirmed matches. Its response has only `planned_requests`, `planned_questions` and `candidates`. The first preview also warms the catalog vector cache.

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
| `retrieval_miss` | The selected scope contains no candidates; review the catalog and scope. A nonempty semantic index returns nearest candidates even for unrelated input. |
| `no_compatible_shortlist_candidate` | Review reported contradictions and search coverage. |

`complete_inference` means all planned scoring calls returned validated answers; it does not measure their accuracy. `requires_review` is always `true`: catalog coverage, lifecycle/applicability and categorical text evidence are still experimental. `warnings` exposes unresolved alternatives, conflicting values, truncated retrieval and numbers that could not be bound. `clarifying_question` is `null` when no further input question is needed, but review can still remain.

| HTTP status | Meaning |
|---|---|
| `200` | Processing succeeded; inspect the analysis status. |
| `422` | Invalid input or a plan exceeding the question budget. No classifier calls are submitted; embedding retrieval may already have run. |
| `502` | Embedding retrieval or classifier failed. Embedding failures return `detail.result=null`; the failed run and error remain in PostgreSQL. Classifier failures return the compact partial result under `detail.result`, including its `run_id`. |
| `503` | A model operation is already running, or the database is unavailable. |

Scoring calls run sequentially and stop at the first failure, without automatic retries. A timed-out upstream request may still be running; check the classifier before resubmitting. The lock only covers this process and cannot cancel or track remote work after timeout. Use **one Uvicorn worker**. Analysis waits for completion and can take several minutes; the timeout applies separately to each upstream call. There is no background queue.

If Swagger displays `TypeError: NetworkError when attempting to fetch resource`, the browser did not obtain a usable response. This message alone does not identify the cause. An ordinary HTTP `502` or `503` is a readable response rather than a rejected Fetch promise; see [MDN's Fetch documentation](https://developer.mozilla.org/en-US/docs/Web/API/Window/fetch). Network/proxy interruptions, browser blocking, or server reloads can interrupt delivery. A timeout is one possibility, not an established diagnosis.

`/analyze` runs in a worker thread and can continue after the browser disconnects, saving its result normally. This implementation does not cancel inference on disconnect. Avoid immediately resubmitting: inspect `/health` for `model_busy`, and look for `Analysis started: run_id=...` and `Analysis saved: run_id=...` in the server log. Retrieve a completed result in Swagger through `GET /results/{run_id}`, or inspect `analysis_runs.result` in PostgreSQL. A recovered partial result still has `complete_inference=false`; retrieval itself returns `200` because reading the saved database result succeeded.

To diagnose a recurring browser failure, open Developer Tools → Network before submitting and inspect the failing `/analyze` request's URL, elapsed time, status and browser Console error. Use Swagger served by the same backend (`/docs`) and confirm its request uses the same scheme, host and port. Test without `--reload` while diagnosing interruptions. If using a reverse proxy, inspect its request/read timeout and logs; `CLASSIFIER_TIMEOUT_SECONDS` does not control the browser-to-backend connection. Increasing Uvicorn's keep-alive timeout does not extend an active request: it applies between requests, as shown in [Uvicorn's HTTP implementation](https://github.com/encode/uvicorn/blob/master/uvicorn/protocols/http/h11_impl.py). An asynchronous submit-and-poll API would avoid holding one HTTP connection open for the complete analysis, but the current endpoint remains synchronous.

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
| `BACKEND_MAX_QUESTIONS` | `128` |
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
uv run --locked python -m unittest discover -s experiments -p 'test_*.py' -v
# Real PostgreSQL checks create and remove isolated test schemas.
RUN_POSTGRES_TESTS=1 uv run --locked python -m unittest discover -s backend/tests -v
```

Tests cover embedding transport, semantic retrieval without shared words, scope filtering, deduplicated vector caching, cache invalidation, service failures, unresolved alternatives, contradictory accepted facts, numeric rule uncertainty, unit conversion, required fields, compact responses, saved evidence and partial failures. They use fake embeddings and a fake classifier; these checks verify the pipeline rather than real-model retrieval or prediction quality.

PostgreSQL integration tests verify migrations, persisted catalogs, pgvector ranking, atomic index replacement, pre-dispatch commits, criterion order, restart recovery, partial failures, embedding request records and idempotent legacy import. They use the database configured in `.env` with isolated schemas.
