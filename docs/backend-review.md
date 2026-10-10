Review dated **2026-10-10**. The backend implements a persistent candidate-search and constraint-checking prototype. It does not yet complete the brief's editable, progressive workflow through to a validated final KTRU code.

This review compares [the implementation plan](implementation-plan.md), [the original flow diagram](../data/implementation_plan.png), [the task brief](../data/task.pdf), the supplied evaluation criteria, and the current source. All rows in the three XLSX workbooks and every record in the 82 `all_actual` XML files were scanned again. PostgreSQL was inspected read-only. The fresh data measurements are in [backend-data-review.json](backend-data-review.json); no source data or database records were changed. No new model inference or accuracy benchmark was run.

**Data and current coverage**

| Source | Fresh count | Used by the backend |
|---|---:|---|
| Actual-file KTRU | 81,465 records; 81,463 distinct code/version keys | Imports an exploratory subset of ACTIVE, specific positions |
| ACTIVE KTRU | 60,087 records, including 5,897 templates | Templates are discarded; application dates are retained but not enforced |
| STE product sheets | 299,986 products | Not imported or searched |
| Portal template sheets | 106,652 rows; 106,185 pass the structural check; 617 categories | Not imported or used as vocabulary |
| SPGZ references in Portal templates | Property IDs/names and listed values | Not imported; these are not a standalone SPGZ product catalogue |

The current folder contains the 82 actual XML files, three workbooks and supporting documents. The historical `not-actual` files and nested ZIP mentioned in the older data report are no longer present. Their absence does not change the actual-file record counts above.

The runtime catalogue contains **1,302 positions, 283 distinct normalized product names and 2,568 categorical facts**:

| Domain filter | Positions | Distinct product names | Positions without characteristics |
|---|---:|---:|---:|
| Clothing/footwear: rubric 116 | 922 | 121 | 25 |
| Furniture: rubric 128 | 190 | 90 | 3 |
| Tools: prefixes 25.73.* / 28.24.* | 190 | 72 | 17 |

`scope="all"` means the union of these filters. These are not a reviewed crosswalk covering every product in the three workbooks. For example, the catalogue already includes `Табурет` and several chair names, but retrieving the right code for `Табуретка` still needs an evaluated semantic-retrieval case.

Important source findings remain:

- There is no supplied STE-to-KTRU or KPGZ-to-KTRU crosswalk. STE descriptions are realistic inputs, not labelled answers.
- 467 template rows fail the structural check. A further 2,065 structurally valid rows contain unresolved value-ID placeholders. They must not become allowed categorical values.
- The actual KTRU files include 21,378 TERMINATED records, two repeated code/version keys and 2,203 unresolved parent-version references on ACTIVE records. Production import needs explicit provenance and eligibility policies.
- **75 of the 1,302 imported positions have application start dates after 2026-10-10.** The importer currently leaves these for review; an explicit evaluation-date policy is still needed.
- **45 imported positions have no characteristics.** An empty rule set cannot by itself establish a final match.
- Quantitative values in the subset use 17 unit-code entries, including the absent/dimensionless unit. Online binding currently supports only `003` (mm), `222` (V), `212` (W) and `263` (A·h). Counts, mass, area, volume and other units are not covered. Text in cm/m is converted to mm; it is not subsequently converted into a candidate rule stored in OKEI `004`/`006`.

**What is implemented**

The actual online flow is description → semantic name retrieval → candidate-specific classifier questions → deterministic checks → explained provisional candidates and a clarification question. Characteristic names and categorical alternatives come from KTRU. `jiwo-4b` classifies the supplied hypotheses; Python constructs the output and question text.

- [Catalogue import](../experiments/classifier_experiments.py) streams all actual XML parts, applies the exploratory domain/status/template filters, preserves code/version identities and source files, rejects conflicting selected duplicate records, and retains characteristic type/kind/required flags, value ordinals, exact numeric values and interval boundaries. Non-current characteristics are excluded.
- [Embedding retrieval](../experiments/embedding_retrieval.py) embeds unique product names with `google/embeddinggemma-2`, embeds each incoming description, ranks by cosine similarity, and preserves code/version alternatives. Defaults select up to four distinct names and eight positions. It does not embed STE products, characteristic definitions or complete position descriptions.
- [Pipeline checks](../experiments/classifier_pipeline.py) preserve supported/contradicted/unknown/conflicting states, require product-identity support, apply a configurable uncalibrated threshold, bind supported point measurements to properties, and check exact values and open/closed numeric bounds. Missing required fields are recorded; unknown information alone does not eliminate a candidate.
- [FastAPI](../backend/src/routes.py) provides `/preview`, `/analyze`, `/results/{run_id}` and health checks. [PostgreSQL storage](../backend/src/storage.py) persists catalogue snapshots, pgvector embeddings, runs, complete outgoing requests, responses, failures and startup checks. INFO logs show concise progress; DEBUG retains request detail.
- The backend reuses the prepared catalogue at startup and builds/loads the name index lazily on the first search. Cache identity includes the model, prompts and names. This differs from the plan's proposed offline preparation.
- The existing tests cover protocol validation, interval boundaries, uncertainty, cache reuse, partial failures, API contracts and database persistence. They are development/regression checks, not a held-out final-code evaluation.

PostgreSQL currently has one catalogue snapshot (1,302 positions / 2,568 facts), one **283-vector, 768-dimensional** index, 11 analysis runs and 169 classifier-call records. The latest saved run, `20261010T192540359120Z_255b9aecad5f4f9096ccacb358aa5794`, reused the in-memory embedding index and completed 19 `jiwo-4b` requests / 61 questions. Its result was `needs_clarification`. It took approximately **18.1 seconds**, including 1.25 seconds for retrieval and 16.05 seconds in classifier requests. This is one observed run, not a p95 or quality result.

**Status against the seven milestones**

Subsequent batching work added `CLASSIFIER_BATCH_SIZE=16` to the backend and pipeline CLI. Product, categorical and numeric checks are packed into shared-description requests; source jobs and question-ID mappings remain available in saved evidence. The installed jiwo revision already supports GPU batching, so no server API change was required. The live check used 4 requests for the same 61 questions previously sent in 19 calls. Classifier time was 7.56 seconds versus 16.05 seconds in the earlier run, with all selected answers unchanged. It reused the saved semantic shortlist because the embedder timed out; this is not a fresh end-to-end retrieval or p95 benchmark. All 91 regression/integration tests passed, including batch failures, repeated numeric question IDs, replay and real PostgreSQL persistence.

| Milestone | Status | Work still needed to meet its acceptance condition |
|---|---|---|
| 1. Acceptance cases and evaluation | Partial: hand-authored diagnostic fixtures exist | Independently reviewed examples across all three domains; acceptable code sets, expected facts and abstention labels; held-out split |
| 2. Catalogue and vocabulary | Partial: repeatable exploratory KTRU import and persistent snapshots | Full required metadata/provenance; lifecycle policy; parent/template handling; reviewed scope; Portal/STE import and quality quarantine |
| 3. Retrieval and extraction | Partial: embedding search, candidate fact checks and point-measurement binding | Recall measurement, source spans for categorical facts, invalid/unseen values, broader units, input ranges/comparisons and contextual mappings |
| 4. Validation and clarification | Partial: categorical/numeric checks, required fields and template questions | Complete application rules, applied user confirmations, retrieval widening, useful next-question selection and final-code eligibility |
| 5. Complete web workflow | Partial: analysis API and saved results | Editable fact/session contract, update history, structured clarification answers, snapshot ID in public responses, browser UI |
| 6. Quality and performance | Partial: diagnostics and stage timing evidence | Current-model held-out quality report, retrieval ablation, threshold calibration, domain-level metrics, p50/p95 and resource measurements |
| 7. Deployment and defense | Partial: pinned dependencies, env configuration, PostgreSQL Compose and launch docs | Rebuild/publish commands, prepared indexes, complete app/model deployment, required BPMN, reproducible three-domain demo |

No milestone is complete against all of its original acceptance conditions. Several useful components within them are complete.

**Specific workflow gaps**

1. **Edits currently do not validate or narrow candidates.** `extras` accepts name/value fields and records `map_and_validate`, `review_before_add`, etc. These labels describe proposed actions: the values are not actually fed into categorical/numeric checks or used to satisfy required fields. A clarification answer must currently be folded manually into the input text and submitted as a new run.
2. **Categorical extraction is limited to supplied alternatives.** Facts have no verified original text span. A value absent from every shortlisted schema is not independently extracted and checked; it can remain unknown instead of producing a specific invalid-value explanation. Arbitrary text properties are not generated.
3. **Application rules are incomplete.** `kind=3` affects ambiguity handling, but this is not a complete implementation of all kind rules. Product units, parent metadata, cancellation information, `valueFormat` and additional-feature reasons are not retained in the runtime schema. All 1,302 selected positions have `noNewFeatures=false` or an absent flag; prohibition cases therefore need separate acceptance cases as well as the existing synthetic tests.
4. **Shortlist search has no recovery loop.** Embeddings use names only, with no acceptance cutoff. There is no automatic widening after rejection or ambiguity. Public candidates are grouped by assessment and sorted by code/version; retrieval similarity is not an explained final ranking. Similarity is not a match probability.
5. **The original diagram's correction and SPGZ branches are absent.** A LanguageTool client/CLI exists outside the backend, but analysis does not call it. The supplied SPGZ references can enrich vocabulary and reviewed mappings; implementing a fallback search over a presumed SPGZ product dataset would require data that is not supplied.
6. **There is no final-code output.** Detailed reports always set `final_code=None`; public results always set `requires_review=True`. A provisional recommendation does not complete the final-code milestone.

**Further steps, in dependency order**

1. **Establish a small reviewed acceptance set immediately.** Start with roughly 10 cases per domain, then expand toward the plan's 90. Include `Табуретка`, real STE descriptions, future-date records, empty schemas, invalid categorical values, unit conversions, input ranges, corrections and indistinguishable codes. Record all acceptable codes and cases where no final answer should be issued. Re-evaluate `jiwo-4b`; older classifier results do not establish its quality.
2. **Finish the import boundary.** Define reviewed three-domain coverage and evaluation-date eligibility; preserve source occurrences, templates, parent/version references, product units, cancellation metadata, value format and additional-feature reasons. Add conservative Portal/STE import with row provenance, quarantine and SPGZ property links. Add an explicit rebuild/validate/publish command so source changes create a new snapshot rather than silently continuing to use the previous database catalogue.
3. **Make structured user facts executable.** Introduce facts with source spans, separate values/units, scalar/range/comparison types, confidence and confirmation status. Apply user confirmations and corrections through the same deterministic validator. Add dimension-aware conversion into each candidate's actual OKEI unit, dimensionless counts and the units used by furniture/clothing. Extract unsupported categorical values explicitly so invalid input can be explained. Preserve physical-plausibility warnings separately from catalogue constraints.
4. **Complete narrowing and final eligibility.** Apply remaining kind/lifecycle/required/extra-property rules; measure retrieval recall and compare name-only embeddings with richer text or lexical support. Widen retrieval when needed. Return a final code only when semantic support, applicable rules and mandatory information are resolved and alternatives have been adequately considered; preserve legitimate ties.
5. **Deliver the clarification loop and UI.** Add an analysis/session revision contract, structured question choices, confirmed fact updates and candidate history. Revalidate known facts without rescoring everything; allow corrections to restore candidates. Build editable rows, clear missing/invalid-field explanations and progressive counts in a browser. Connect the LanguageTool suggestion/acceptance flow. Use background jobs and polling/progress if analysis stays too slow for an interactive request.
6. **Measure, optimize and package.** Run the held-out suite and report quality by domain/scenario, recall@k, false confident answers, clarification success, p50/p95 and inference resources. HTTP/GPU batching is now implemented; further reductions need relevant-fact selection, verified reuse and measured batch-size/kernel tuning. Prepare the Linux deployment/rebuild instructions, BPMN and three-domain demonstration.

The next useful implementation slice is **confirmed fact edits → correct unit/value validation → a persisted clarification answer**, exercised on one reviewed family in each domain. This would close a central workflow gap while the broader import and evaluation work proceeds.
