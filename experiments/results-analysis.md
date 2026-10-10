Review of the rerun artifacts saved on 2026-10-10, 10:39–10:57 UTC. The results support using Nimble to check characteristics within a retrieved product family. They reproduce the earlier extraction failures and do not establish final КТРУ accuracy.

All ten saved summaries were recomputed from their raw request logs: experiment metrics, confusion rows and baseline counts match. This review makes no new model requests.

**What actually ran.** There are 20 run directories: ten complete runs, three partial inference logs, one startup failure, one health-only directory and five empty directories. The ten complete runs contain 84 HTTP inference requests, 189 questions and 95.07 seconds summed client inference time. Including partial logs gives 111 saved inference responses, 294 answered questions and 147.80 seconds. No saved inference response is an API error; this does not make the incomplete runs successful.

The startup failure in `20261010T103926767202Z_smoke` is connection refused at localhost:8769. The progressive directories `20261010T104054342240Z_progressive` and `20261010T104806553435Z_progressive` each contain 13 of 20 planned requests (52 of 80 questions), without a summary or recorded error. `20261010T104745278147Z_slots` contains 1 of 9 requests. Their stopping reason is not saved; do not infer a timeout, model failure or deliberate interruption from these files. `20261010T104746305159Z_facts` contains only health metadata. Empty directories contain no prediction evidence.

There is no saved live follow-up run, `followup_report.json`, or pipeline `analysis.json` in this snapshot. The README previously listed `--suite followup --dry-run` among live focused suites, so following that command prepared requests without inference. That placement has been corrected: the offline section retains the preview and the live section now runs the suite. Likewise, the pipeline example with `--dry-run` does not test its new name/constraint flow. There is no persisted unit-test console output to audit here; offline tests check implementation behavior and cannot measure model quality.

**Completed runs.** The timings below are sums of HTTP request wall times, not full command runtime or isolated GPU throughput. “Manual” means labels were inferred during this review from the explicit synthetic description; those labels are not in the saved run. Repeated examples are not independent benchmark samples.

| Run | Quality evidence | Sum of request times |
|---|---|---:|
| [Smoke](results/20261010T104013466966Z_smoke/summary.json) | 15/16 saved labels; fact status 11/12, domain routing 4/4 | 7.94 s |
| [Numeric, first](results/20261010T104035421849Z_numeric/summary.json) | 5/6 saved labels | 2.92 s |
| [Numeric, repeat](results/20261010T104748327861Z_numeric/summary.json) | 5/6; identical answers/probabilities to first | 2.73 s |
| [Slots, first](results/20261010T104038660874Z_slots/requests.jsonl) | Manual 7/9; two unsupported additions | 4.55 s |
| [Slots, repeat](results/20261010T104751745098Z_slots/requests.jsonl) | Same 7/9; identical answers/probabilities | 3.82 s |
| [Facts, first](results/20261010T104043564149Z_facts/requests.jsonl) | Manual 20/20 statuses | 10.42 s |
| [Facts, repeat](results/20261010T104755904454Z_facts/requests.jsonl) | Same 20/20; identical answers/probabilities | 10.27 s |
| [Progressive, complete](results/20261010T105448193200Z_progressive/summary.json) | Manual 78/80 statuses; two errors | 40.78 s for four descriptions |
| [Option order](results/20261010T105609919717Z_order/summary.json) | 3/3 saved labels; original, reversed and repeated options | 1.37 s |
| [Facts, custom text](results/20261010T105657852556Z_facts/requests.jsonl) | Manual 20/20 statuses | 10.27 s |

The manual rule is: explicitly stated characteristics are supported, their incompatible alternatives are contradicted, and unmentioned characteristics are unknown. `correct: 0, labeled: 0, accuracy: null` in slots/facts/progressive means automatic accuracy was not measured, not that every prediction was wrong.

**Smoke.** The same deliberately inconsistent power description still selects contradicted (0.5074) over the expected conflicting (0.4656). Everything else, including negation, typo, packaging evidence and the four simple domain routes, passes. For a fair baseline comparison, use the 12 fact-status cases: Nimble 11/12 (91.7%) versus exact-value matching 3/12 (25%). The combined 15/16 figure includes four routing questions the baseline does not answer. This is development-fixture performance, not real-description or final-code accuracy.

**Numeric binding.** Both complete runs select the correct battery voltage, distinguish the battery from the 220 V charger, abstain on charger-only/missing voltage, and detect conflicting voltages. Both miss `Напряжение аккумулятора дрели 0,018 кВ.`: unknown 0.5441 versus the correct span 0.4304. The parser already produces 18.000 V; ownership selection remains the model failure. Exact repetition yields the same probabilities, so this failure did not disappear on rerun. The new raw-versus-normalized follow-up has not yet been measured.

**Slots versus independent facts.** Both slot runs infer “one battery included” (0.4905) and “angular construction” (0.7284), although neither appears in the description. The other seven slot decisions agree with manual interpretation. At a 0.8 acceptance threshold, both unsupported additions are withheld on this input. Without abstention, only 3 of the 5 selected concrete values are supported by the description (60% positive-value precision).

All three complete independent-fact scans produce three supported, three contradicted and fourteen unknown statuses; all 20 statuses agree with manual interpretation. The supported facts are battery power, reverse=yes and impact=no. They leave battery count and construction unknown. This is more conservative on these inputs, but costs twenty questions and roughly 10.3 seconds, versus nine questions and 3.8–4.6 seconds for slots. The two identical default-text runs have exactly identical distributions; the custom-text run supplies only a second closely related wording.

**Progressive narrowing.** The completed run retains 2 → 1 → 1 → 1 positions as the description adds battery power, reverse and no impact. Each input takes approximately 9.90, 10.44, 10.26 and 10.18 seconds. Battery power excludes `28.24.11.000-00000001@5` and retains `28.24.11.000-00000002@4`. Reverse and impact allow both yes/no values in both positions, so they do not distinguish the pair.

Two status errors are hidden by these plausible candidate counts:

- With only `Нужна дрель.`, impact=yes is invented with supported probability 0.8481. It exceeds the default threshold. Both catalog positions allow impact mode, so the invented fact removes neither candidate.
- With `Нужна аккумуляторная дрель с реверсом.`, reverse=no is classified unknown (0.7820), rather than contradicted.

Across the complete progressive run, 78/80 status accuracy is 97.5%, but supported-fact precision before thresholding is only 6/7 (85.7%): one of seven positive facts is invented. At threshold 0.8, the true impact=no fact in the final description is withheld (0.6899), while the invented impact=yes fact is accepted (0.8481).

| Threshold, uncalibrated | Accepted positives | Correct / invented | Supported precision | Supported recall |
|---|---:|---|---:|---:|
| 0.6 | 7 | 6 / 1 | 85.7% | 100% |
| 0.8 | 6 | 5 / 1 | 83.3% | 83.3% |
| 0.9 | 5 | 5 / 0 | 100% | 83.3% |
| 0.95 | 4 | 4 / 0 | 100% | 66.7% |

These values are a sensitivity analysis on the same development examples, not threshold calibration or evidence that 0.9 will generalize. The true impact=no fact scores 0.9217 in the default facts run, 0.6899 in the progressive final text and 0.9744 in the custom text. Wording changes both scores and threshold decisions. Evidence checking and independently reviewed evaluation cases are needed before treating accepted facts as reliable.

**What the surviving code means.** It is compatible within a preselected two-position electric-drill family. These runs did not retrieve products or score the pipeline's candidate names. The categorical suite does not apply required numeric rules. The battery position requires power supply, minimum and maximum chuck diameter, maximum RPM, battery capacity and battery voltage. Power is extracted; the sample contains voltage, but categorical narrowing does not bind/validate it; the other four required measurements are absent. Thus narrowing to one code is not complete specification validation.

**Repeatability and latency.** The repeated numeric, slots and default-facts requests yield exactly identical answer distributions. The two partial progressive logs also match one another; the completed progressive run reproduces the noted failures. Reversing choice order leaves the answer supported; the largest probability shift is 0.002626, or 0.263 percentage points, and the identical repeat is identical. This establishes repeatability only for these tested requests, including their mistakes.

Fact scans now take about 10.3 seconds versus the prior review's 10–14-second range. Smoke and slots are also faster than the prior recorded examples. There is no controlled performance comparison, so shared-server load and runtime state may explain the difference. Four-fact HTTP requests have approximately 2.1-second medians. Extrapolating twenty-fact runtime to 2,568 facts still gives about 22 minutes per input; no full scan was measured.

All saved health files report the same base revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`, NF4 double quantization, FP16 compute and Tesla V100-SXM2-32GB, with 8.01 GiB allocated at the health snapshot. That is not peak inference memory, and health does not identify the adapter revision. All recorded catalog hashes are the same.

**Next evidence to collect.** Run the follow-up without `--dry-run` to test normalized numeric representations and clearer conflicts/corrections across the three domains. Then run the Python pipeline live to test product-name relevance, numeric ownership, required-field reporting and extras. Those tests are not covered by the current family categorical scans.

```bash
uv run --locked python experiments/classifier_experiments.py --suite followup

uv run --locked python experiments/classifier_pipeline.py \
  --text 'Нужна аккумуляторная дрель 18 В с реверсом, без ударного режима.'
```

The current evidence supports family-scoped fact checking with explicit unknowns and review. It does not yet support exhaustive free-form characteristic extraction, measured retrieval recall, robust conflicting-input handling or final-code selection.
