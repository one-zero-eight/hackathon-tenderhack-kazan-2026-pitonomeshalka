Build a Linux web application that turns a Russian product description into editable, normalized characteristics, progressively narrows eligible KTRU positions, and either returns a supported final code or asks a specific clarifying question.

The core design is **candidate retrieval followed by explicit KTRU constraint checking**. KTRU controls the allowed characteristics, values and units. Portal category templates and STE descriptions provide vocabulary and realistic examples. Their missing links to KTRU must be inferred and evaluated.

This plan follows [task.pdf](../data/task.pdf) and the [data relationship analysis](../data/data-relationships.md). It proposes milestones in dependency order; calendar estimates depend on team size, available hardware and the hackathon deadline.

**Architecture.** Start with one Python application containing separate modules for import, retrieval, normalization, validation and dialogue, plus a browser interface and a local catalogue database/search index. Import and index the data offline; requests use the prepared snapshot. Keep model inference optional and replaceable. Separate services only if measured load or deployment constraints justify them.

| Component | Responsibility | Main output |
|---|---|---|
| Offline data pipeline | Parse XML/XLSX, preserve source records, validate structure, prepare the canonical catalogue | Versioned catalogue, vocabulary, import quality report |
| Candidate retrieval | Find plausible KTRU positions from product meaning and normalized facts | Ranked candidates with retrieval evidence |
| Extraction and normalization | Identify characteristics, values, negation and units; map them in candidate context | Structured facts with original text spans and mapping confidence |
| Constraint engine | Check applicability, required fields, categorical choices, units, numeric ranges and conflicts | Per-candidate matches, contradictions and unknowns |
| Clarification engine | Choose the next useful question and explain unresolved ambiguity | A question with supported answer choices, or a correction request |
| API and session state | Recompute results after edits and preserve the explanation history | Consistent analysis responses and narrowing steps |
| Web interface | Accept text, expose editable facts, candidates, warnings and questions | Complete user workflow |

The online sequence is: extract initial facts → retrieve candidates → resolve characteristics in their context → validate → rank survivors → return a result or ask for clarification. Each user edit reruns the relevant steps. A reviewed correction can broaden the candidate set again.

**Milestone 1 — Define acceptance cases and evaluation before optimizing.**

Create a small manually reviewed reference set across tools, furniture and clothing. Start with a few cases per domain to guide implementation and grow toward roughly 90 cases, balanced across the three domains. Include clear matches, several valid codes, missing characteristics, typos, conflicting facts, invalid units/values and descriptions outside supported coverage.

For each case, record the expected normalized facts, acceptable KTRU code(s), source evidence, and whether the correct response is a final code, clarification or no supported match. The 299,986 STE rows have no verified KTRU labels; use them as input examples, not as ground truth. Keep cases used to tune aliases or models separate from the final evaluation cases, grouping near-duplicate products together. Report synthetic constraint tests separately from independently reviewed product examples.

**Done when:** each domain has reviewed examples and the team can distinguish a correct final answer from correct abstention.

**Milestone 2 — Build a reliable catalogue and supporting vocabulary.**

Import all `all_actual` XML parts with a streaming parser. Preserve status, dates, cancellation metadata, template flags, characteristic rules, units, classifications and source locations. Exclude `not-actual` inputs as the brief requires. Define candidate eligibility for an explicit evaluation date; an “actual” filename alone is insufficient because these files contain terminated records. Keep parent templates for navigation and explanation, and return specific positions as final results.

Use `(code, version)` for KTRU identity and scope characteristics to that version. Preserve raw occurrences before resolving duplicate keys. Retain unresolved parent-version references without substituting a different version's constraints. Keep product units distinct from characteristic units, and preserve open/closed range boundaries and missing value IDs.

Import Portal templates, explode SPGZ ID lists, and retain row-level provenance. Quarantine the known malformed/shifted rows and unresolved-value placeholders; apply only verifiable repairs. Parse STE characteristic strings conservatively and keep the original text. Build dictionaries of names, synonyms, categorical values and unit aliases, with the source and status of every inferred mapping.

Scope the application to clothing, furniture and tools using a reviewed combination of rubricators, OKPD2 and product names. Avoid requiring a Portal category or a KPGZ-to-KTRU crosswalk: neither is available for every product. Reuse sound findings from the existing cleaning notebook in the repeatable import pipeline.

**Done when:** imports are repeatable, counts reconcile, every normalized record is traceable, and unresolved data issues are visible in a quality report.

**Milestone 3 — Retrieve candidates and extract usable facts.**

Build a lexical retrieval baseline over KTRU names, characteristic names, allowed values and reviewed aliases. Use Russian text normalization and conservative typo matching. Add category/OKPD2 context as supporting evidence while allowing recovery from an uncertain initial category guess.

Extract numbers, ranges, units and known property/value phrases first. Then use candidate-specific characteristic definitions to resolve ambiguous terms such as “размер”, “мощность” or “материал”. Preserve negation, comparison operators and multi-value statements. Distinguish the product from its packaging or accessories when assigning measurements.

Represent each extracted fact with its original text span, normalized value/unit, candidate characteristic mapping, confidence and confirmation state. Convert units only when dimensions are compatible. Apply unambiguous spelling/format normalization with a visible explanation; ask before changing the meaning or a numeric value.

Start with one product family to prove the workflow, then expand the same mechanism across all three domains. If retrieval misses reviewed examples, measure whether a small open embedding model improves recall. Add a reranker or open text model only for a demonstrated remaining weakness.

**Done when:** the expected code is retrieved reliably on reviewed cases, extracted facts retain evidence, and uncertain mappings remain explicit.

**Milestone 4 — Validate, narrow and ask useful questions.**

Implement the constraint engine as ordinary deterministic logic. Check characteristic `type`, `kind`, `actual`, `isRequired`, allowed categorical values, numeric intervals, exact values, unit compatibility and `noNewFeatures`. Use `kind` for application-time choice rules; do not substitute `choiceType`. Keep physical-plausibility checks separately identified from catalogue constraints.

For each candidate, distinguish supported matches, confirmed contradictions, missing required information and facts that could not be mapped. Missing information is unknown; it is not automatically a contradiction. A low-confidence extraction should prompt clarification rather than permanently eliminate a candidate. Empty KTRU characteristics are not evidence of a strong match.

Rank candidates by product relevance and explained matches, then remove candidates contradicted by reliable facts. Record which fact caused each exclusion. Make the displayed count clear about its scope: a retrieved shortlist is not the entire catalogue. Widen retrieval when needed before claiming uniqueness or no match; even after widening, express the result within supported coverage.

When several candidates remain, ask about a missing characteristic that best separates them, prioritizing mandatory fields and questions the user can answer. When none remain, identify the conflicting facts or possible coverage gap. When a single candidate remains, still check semantic support, mandatory information and unresolved conflicts before presenting it as final. A top-ranked candidate alone is insufficient.

**Done when:** the system handles one match, several matches and no match with an explanation and an appropriate next step; adding a compatible confirmed fact narrows a fixed candidate pool, while corrections can restore candidates.

**Milestone 5 — Deliver the complete web workflow.**

Expose one analysis API accepting the description and user-confirmed edits. Return normalized facts, original spans, applied corrections, candidate codes, validation results, remaining questions and the narrowing history. Include the catalogue snapshot identifier so results are reproducible.

Build a single main screen with the description input, editable characteristic/value/unit rows, candidate list, and explanations. Display required missing fields and distinguish automatic normalization from suggested semantic corrections. Show why candidates were removed and preserve user edits across updates. Debounce typing and discard stale responses so older analyses cannot overwrite newer input.

Use the supplied Portal UI kit as design guidance during implementation. Keep the experience focused on the product task: entering a description, reviewing corrections, answering questions and receiving a code. Support the Russian names and text present in the data.

**Done when:** a user can complete the scenario from text to result, including incomplete and incorrect input, across all three domains.

**Milestone 6 — Evaluate quality and improve measured weaknesses.**

| What to measure | Why it matters |
|---|---|
| Candidate recall at a fixed shortlist size | Separates retrieval failures from validation failures |
| Characteristic/value/unit extraction accuracy | Tests whether the description was interpreted correctly |
| Final-code accuracy and rate of final answers | Prevents high apparent precision achieved by abstaining on everything |
| False confident answers on ambiguous, contradictory or unsupported inputs | Detects harmful overclaiming |
| Error-detection precision and recall | Checks both missed problems and unnecessary corrections |
| Clarification success and number of questions | Tests whether the user can reach a supported result |
| End-to-end p50/p95 latency, RAM and total inference VRAM | Demonstrates practical performance on the demo hardware |

Keep regression checks focused on meaningful failure modes: interval boundaries, unit conversion, contradictory attributes, missing required fields, lifecycle filtering, duplicate keys, parent-version gaps and ambiguous cases. Report results by domain and scenario. Log stage timings so optimization addresses the actual bottleneck.

Treat a warm-request p95 below two seconds as an initial engineering target to validate on the chosen hardware, not a promised result. Require no known constraint violations in final outputs on the reviewed acceptance suite. Publish sample sizes and remaining failures alongside aggregate metrics.

**Done when:** there is a reproducible evaluation report, the demonstrated scenarios pass, and model additions have a measured benefit over the lexical/rule baseline.

**Milestone 7 — Package the Linux deployment and defense.**

Provide a repeatable Linux launch procedure, pinned dependencies and a documented command for rebuilding the catalogue/index. Load models and indexes once at startup, reuse immutable catalogue data, and isolate each user's analysis state. Explain how catalogue updates replace a snapshot and how API workers can be scaled when required.

Prepare the required BPMN diagram showing description entry, extraction, validation, candidate narrowing, the clarification loop and final selection. Also provide the component architecture and measured resource/latency results.

Rehearse a short demonstration covering all three domains, including a clean match, a typo/unit normalization, incomplete information, contradictory input and a no-match case. Show the original input, the evidence behind corrections, how candidate counts change, and the final outcome. Keep local examples and prepared data available for the defense.

**Done when:** another team member can start the application from the documented steps and reproduce the demo and evaluation results.

**Priorities and boundaries.** The required deliverable is the complete workflow across clothing, furniture and tools, with transparent ambiguity handling. Build a working family-level example early, then expand coverage. Treat learned retrieval, model fine-tuning, large-scale automatic alias discovery and extra operational infrastructure as later work justified by results.

The brief requires Linux and a web interface, prohibits paid search APIs, proprietary external LLM APIs and low-code/no-code platforms, and permits only open ML models with at most 40 GB total inference VRAM. Keep the core operational without an LLM. Choose any optional model only after confirming its terms, hardware fit and evaluation benefit.

The first implementation checkpoint should therefore be: **a reviewed example set, a traceable KTRU importer, and a text-to-candidate-to-clarification workflow running on one representative product family**. Expand that proven path to the other families before spending effort on model complexity or presentation polish.

**Current classifier experiment — 2026-10-10.** The deployed classifier is `jiwo-4b`, selected through `CLASSIFIER_MODEL` in `.env`. Configure `CLASSIFIER_BASE_URL` for its existing API; the localhost example uses port 8769 (`GET /health`, `POST /v1/systemone`); the earlier OpenJev setup is an alternative, not the model used by these experiments. See [experiment instructions](../experiments/README.md), the [interactive notebook](../experiments/classifier_systemone.ipynb), and the [command-line runner](../experiments/classifier_experiments.py).

The experiment sequence is: labeled fact-status/domain diagnostics → numeric span binding → compare catalog slots with independent fact checks → progressive categorical narrowing within a fixed drill family → option-order/repeat/chunking checks → expand to furniture, clothing and the combined exploratory vocabulary. Live classifier and embedding services are now configured through `.env`; requests, responses, health metadata and timings are persisted by the backend in PostgreSQL. Diagnostic experiments support work on milestones 1, 3 and 4; they do not establish current-model accuracy or replace a held-out final-code evaluation.

**Implementation review — 2026-10-10.** A fresh scan of all supplied actual XML records and all six workbook sheets was compared with the current backend and a read-only database inspection. See [the detailed backend review and ordered next steps](backend-review.md) and [fresh measurements](backend-data-review.json).

The backend currently searches 1,302 exploratory KTRU positions through embeddings of 283 product names, checks candidate facts with `jiwo-4b`, validates supported point measurements, and persists evidence/results in PostgreSQL. Catalogue/vocabulary import, extraction, validation, the API workflow, evaluation and deployment are each partially implemented. Portal/STE imports, complete lifecycle/application rules, executable user edits, clarification sessions, a browser UI and validated final-code output remain outstanding. The original milestone acceptance conditions are retained above; implemented infrastructure alone does not mark those milestones complete.

Next priorities are a reviewed three-domain acceptance set, complete import metadata and eligibility, then structured confirmed facts with broader unit/range validation. Use these to finish the clarification loop and final-code eligibility, deliver the editable web interface, and measure/package the resulting workflow. The next useful implementation slice is confirmed fact edits → correct unit/value validation → a persisted clarification answer.

**Batching update — 2026-10-10.** The installed jiwo deployment already batches questions on the GPU. The backend and pipeline CLI now combine product, categorical and numeric checks into requests of up to `CLASSIFIER_BATCH_SIZE` questions (16 by default, configurable in `.env`). Full request evidence and original check mappings remain persisted. A live classifier check reduced the drill example from 19 HTTP calls to 4 for the same 61 questions, with all selected answers unchanged; classifier time was 7.56 seconds versus 16.05 seconds in an earlier run. Retrieval reused a saved shortlist because the embedder timed out, so this does not establish end-to-end latency.
