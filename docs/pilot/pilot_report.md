# VerifyLoop real-model pilot report

**Date:** 2026-10-20  
**Model:** `llama3.2:3b` via native Ollama `/api/chat`  
**Benchmark:** `benchmarks/synthetic/v1`  
**Patch format:** `edit_json`  
**Runs:** `run-20261020-034833-5bcb12`, `run-20261020-090734-fbc80c`  
**Status:** execution completed; **the evidence-guided contrast was not exercised often enough to compare strategies.** No strategy is claimed superior, and no significance test is interpreted.

---

## 1. Question

Does structured test evidence on a retry improve verified bug-fixing by a small
model, compared with a single attempt or a blind retry?

This pilot is a feasibility check, not a powered experiment. It asks whether the
three conditions can be run under identical mechanics and whether the treatment
(evidence) is actually delivered often enough to learn anything from the
comparison.

---

## 2. Frozen configuration

The exact configuration is [`config/pilot_ollama.yaml`](../../config/pilot_ollama.yaml).

| Setting | Value |
|---|---|
| Provider | `ollama` (native `/api/chat`, not the OpenAI shim) |
| Base URL | `http://localhost:11434` |
| Model | `llama3.2:3b` |
| Authentication | none |
| Temperature / seed | `0.0` / `0` |
| Maximum output | 700 tokens (`max_output_chars` 6000) |
| Patch format | `edit_json` |
| Tasks | `exception_json_005`, `return_missing_009`, `sorting_records_007`, `validation_age_003`, `validation_csv_016` |
| Conditions | `oneshot`, `blind_retry`, `evidence_guided` |
| Trials | 1 per task × condition |
| Max attempts | 2 (one-shot's strategy policy stops at 1) |
| Max model calls | 3 per task × condition |
| Max total tokens | 30,000 per task × condition |
| Max wall clock | 300 s per task × condition |
| Request timeout | 120 s |
| Test timeout | 120 s |
| Execution | sequential; allowlisted `python`/`pytest`; isolated temporary workspaces |

The model was already installed locally. Nothing was downloaded automatically.
The mock provider and all previous experiment records were left unchanged.

---

## 3. Task selection and audit

Selection criteria were declared before the runs:

- one Python source file, at most 15 lines;
- at least three visible tests and three hidden evaluation tests;
- every hidden test implied by the task description, with no unstated requirement;
- deterministic, standard-library only, no external services;
- easy or medium difficulty.

### Selected and analyzed

| Task | Category | Difficulty | Source size | Visible / hidden tests |
|---|---|---|---:|---:|
| `return_missing_009` | return_value | easy | 10 lines | 3 / 6 |
| `sorting_records_007` | sorting_filtering | easy | 6 lines | 3 / 5 |
| `validation_age_003` | input_validation | easy | 10 lines | 4 / 6 |
| `validation_csv_016` | input_validation | medium | 6 lines | 4 / 5 |
| `exception_json_005` | exception_handling | medium | 12 lines | 3 / 6 |

All five selected tasks passed the benchmark validation gate: the baseline fails,
the reference fix applies, and both visible and hidden suites pass after the fix.

### Test-quality conclusions for the selected tasks

- `validation_age_003`: hidden tests cover inclusive bounds, negatives, booleans,
  floats, and values just inside the bounds. The visible suite covers the typical
  case and the two out-of-range errors. Correctness and type/regression behavior are
  measured.
- `sorting_records_007`: hidden tests cover tie-breaking in both sort directions,
  input mutation, a custom key, and empty/single input. Regression safety is
  measured.
- `return_missing_009`: hidden tests cover the list type, empty result, preserved
  order, duplicates, both-empty input, a superset, and generator input. Regression
  safety is measured.
- `validation_csv_016`: hidden tests cover quoted commas, escaped quotes, empty
  fields, and trailing commas; these follow directly from the required `csv` module.
  Plain lines and the empty line are covered by the visible suite.
- `exception_json_005`: hidden tests cover `ValueError`, exception chaining, the
  missing-file default, directory `OSError` propagation, and nested round-trip.
  Correctness and regression safety are measured.

The three excluded boundary tasks are excluded precisely because one or more of
their hidden tests was not implied by the task description or did not measure the
claimed property.

### Excluded during the audit

| Task | Reason |
|---|---|
| `boundary_paginate_001` | Hidden `test_accepts_iterators` requires iterator support that the task description never states. A correct fix for the described bug can fail this hidden test. |
| `boundary_stats_002` | Hidden `test_accepts_generators` requires `mean()` to accept a generator, which the description does not state. |
| `boundary_binary_015` | The hidden `test_large_sequence_is_logarithmic` checks correctness on 10,000 items but does not measure complexity. A linear scan would pass despite violating the stated O(log n) requirement. |
| `multifunc_*`, `multifile_*` | Hard, multi-function or multi-file tasks outside the small-task pilot. |

No task definition, visible test, hidden test, scoring rule, or success criterion
was changed. The audit script is
[`scripts/audit_pilot_tasks.py`](../../scripts/audit_pilot_tasks.py).

### Post-run exclusion

`exception_json_005` was excluded from the comparative analysis after measurement.
Its visible tests use pytest's `tmp_path` fixture. With the 3B model resident, that
suite took **97–120 s** in the controller, versus **2–5 s** in isolation and before
the model was loaded. One cell timed out at the baseline check. This is an
environment/task interaction, not a model or strategy difference, and it makes the
cell's timing and feasibility non-comparable. The raw records are preserved; they
are simply not counted as evidence about the strategies.

---

## 4. Fairness audit

All conditions share:

- the same controller, initial prompt, repository context, and task snapshot;
- the same patch parser, validator, applier, protected-path rules, and size limits;
- the same feedback policy (`pytest tests`) and independent final policy
  (`pytest eval_tests`);
- the same model, temperature, seed, patch format, resource ceilings, and test
  environment;
- the same final evaluation on a fresh workspace with hidden tests.

The intended differences are only:

| Condition | Difference |
|---|---|
| `oneshot` | Stops after one attempt; never sees an outcome. |
| `blind_retry` | Retries while attempts remain; retry says only that the patch failed. |
| `evidence_guided` | Retries with per-test statuses, clipped messages, traceback excerpts, regression indicators, changed files, and remaining budget. |

Patch-rejection feedback is given to **both** blind and evidence, because a patch
that never ran is a format/scope problem rather than test evidence. When the first
patch is rejected, the two retry prompts are therefore identical. This is by
design, but it is also why the evidence contrast was rarely activated in this
pilot.

### Two reporting/correctness fixes made before the second run

1. **One-shot could retry after a provider error.** The model-error branch checked
   only the budget, then called `OneShotStrategy.retry_prompt()`, which raises
   `RuntimeError`. It now calls `_may_retry()`, so one-shot records an
   infrastructure error instead of attempting a retry.
2. **One-shot was mislabeled `budget_exhausted`.** A one-shot run with
   `max_attempts=2` stopped after one attempt and was incorrectly flagged as
   budget-exhausted. The flag is now set only when the strategy would retry and
   the budget actually prevents it.

Both fixes have regression tests. No scoring or task definition changed.

**Tests after the changes:** `python -m pytest -q` → **165 passed in 169.24 s**.
`python -m verifyloop smoke-test` → all three mock scenarios passed.

---

## 5. Execution

### Preflight

OneDrive files in this workspace are on-demand placeholders (`ReparsePoint`). To
avoid first-access stalls, the preflight reads every benchmark file and runs each
selected task's baseline once:

```powershell
python scripts/preflight_pilot.py --config config/pilot_ollama.yaml
```

Result: **115 files / 68.9 KiB hydrated; all five baselines failed as expected**
(`2 passed, 1 failed` etc.), 3.0–4.7 s per task.

### Provider check

```powershell
python -m verifyloop provider-check --config config/pilot_ollama.yaml
```

Result: API reachable, model installed, generation completed in 12.84–14.09 s,
response parsed. Exit code 0.

### Runs

The same command was used twice:

```powershell
python -m verifyloop run --config config/pilot_ollama.yaml
```

| Run | Started | Cells | Total wall | Tokens (prompt + completion) |
|---|---|---:|---:|---:|
| `run-20261020-034833-5bcb12` | 2026-10-20 03:48:33 | 15 | 1,011.2 s | 7,920 (6,901 + 1,019) |
| `run-20261020-090734-fbc80c` | 2026-10-20 09:07:34 | 15 | 918.8 s | 10,030 (8,267 + 1,763) |

Total wall is the sum of per-cell wall clocks, including baseline checks and
timeouts; run 1's total includes four ~120 s infrastructure timeouts.

The second run followed the preflight and was intended as the cleaner repeat. It
is reported separately rather than replacing the first run. The one-shot success
from run 1 did not replicate.

---

## 6. Results

### 6.1 All recorded cells (including the excluded task)

| Run | Verified | Failed tests | Patch rejected | Infrastructure error |
|---|---:|---:|---:|---:|
| Run 1 | 1 | 2 | 8 | 4 |
| Run 2 | 0 | 1 | 13 | 1 |
| **Total** | **1** | **3** | **21** | **5** |

Infrastructure errors were not counted as strategy failures:

- Run 1, `exception_json_005`, all three conditions: baseline `TIMEOUT` at
  122.5 s / 133.9 s / 133.7 s, zero model calls.
- Run 1, `validation_age_003`, blind retry: attempt 2 model request timed out after
  120 s; one attempt had already applied and produced one failing test.
- Run 2, `exception_json_005`, one-shot: baseline `TIMEOUT` at 121.9 s.
- Run 2, `exception_json_005`, blind/evidence: baselines completed but took 97.0 s
  and 101.2 s; the whole task is excluded as environment-affected.

### 6.2 Analyzed cells (four tasks; `exception_json_005` excluded)

**Run 1** (`run-20261020-034833-5bcb12`):

| strategy | cells | valid | verified | failed_tests | patch_rejected | infra | mean attempts | mean wall s | mean tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| oneshot | 4 | 4 | 1 | 1 | 2 | 0 | 1.00 | 46.7 | 486 |
| blind_retry | 4 | 3 | 0 | 0 | 3 | 1 | 2.00 | 37.6 | 760 |
| evidence_guided | 4 | 4 | 0 | 1 | 3 | 0 | 2.00 | 44.2 | 774 |

**Run 2** (`run-20261020-090734-fbc80c`):

| strategy | cells | valid | verified | failed_tests | patch_rejected | infra | mean attempts | mean wall s | mean tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| oneshot | 4 | 4 | 0 | 1 | 3 | 0 | 1.00 | 37.3 | 488 |
| blind_retry | 4 | 4 | 0 | 0 | 4 | 0 | 2.00 | 51.9 | 838 |
| evidence_guided | 4 | 4 | 0 | 0 | 4 | 0 | 2.00 | 37.0 | 788 |

**Combined descriptive totals** (24 analyzed cells; 23 valid + 1 infrastructure):

| strategy | cells | valid | verified | failed_tests | patch_rejected | infra | mean attempts | mean wall s | mean tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| oneshot | 8 | 8 | 1 | 2 | 5 | 0 | 1.00 | 42.0 | 487 |
| blind_retry | 8 | 7 | 0 | 0 | 7 | 1 | 2.00 | 45.8 | 804 |
| evidence_guided | 8 | 8 | 0 | 1 | 7 | 0 | 2.00 | 40.6 | 781 |

Means are over valid cells. Wall time includes baseline checks; test time is zero
for cells whose patch never ran, so test-time means are not directly comparable.

These cells are **not independent trials**. They are two sequential runs of the
same model and tasks. Combined counts are descriptive only.

### 6.3 Task × condition outcomes

| Task | Run | oneshot | blind_retry | evidence_guided |
|---|---|---|---|---|
| `return_missing_009` | 1 | **verified_success** | patch_rejected | patch_rejected |
| `return_missing_009` | 2 | patch_rejected | patch_rejected | patch_rejected |
| `sorting_records_007` | 1 | patch_rejected | patch_rejected | patch_rejected |
| `sorting_records_007` | 2 | patch_rejected | patch_rejected | patch_rejected |
| `validation_age_003` | 1 | failed_tests | infrastructure_error | failed_tests |
| `validation_age_003` | 2 | failed_tests | patch_rejected | patch_rejected |
| `validation_csv_016` | 1 | patch_rejected | patch_rejected | patch_rejected |
| `validation_csv_016` | 2 | patch_rejected | patch_rejected | patch_rejected |

### 6.4 Did the treatment actually get delivered?

| Strategy | Cells with an attempt | First attempt applied | First attempt rejected | Evidence prompts recorded |
|---|---:|---:|---:|---:|
| oneshot | 8 | 3 | 5 | 0 |
| blind_retry | 8 | 2 | 6 | 0 |
| evidence_guided | 8 | 2 | 6 | **2** |

Only **4 of 23 valid analyzed cells ended with tests as the final gate** (1 verified
success, 3 failed tests); the other **19 ended in patch rejection before execution**.
Across all attempts, **7 of 24 analyzed cells** had at least one patch reach the test
suite; the remaining 17 never did. In the evidence condition, a structured test
report was delivered in **2 cells**, both `validation_age_003`. On the other tasks the
first patch was rejected, so the evidence condition received the same patch-rejection
prompt as blind retry and never saw test evidence.

### 6.5 Failure categories (valid analyzed cells)

| Category | Count |
|---|---:|
| `patch_conflict` | 19 |
| `unknown` (failed tests not matching a specific signature) | 2 |
| `syntax_error` | 1 |
| `none` (verified success) | 1 |

`patch_conflict` means the patch never ran: overlapping search/replace edits, a
search string that did not occur, or a hallucinated file such as
`path/to/edit1.py`.

---

## 7. What was observed

### Verified observations

1. **The benchmark contract holds.** `python scripts/validate_benchmark.py`
   validated all 16 tasks. (An earlier validation run hit a transient timeout on
   `exception_json_005`; it passed on repetition and in isolated stress runs
   12/12 times.)
2. **The mechanics are shared.** The three conditions differ only in retry
   information. The two controller defects above were fixed and tested.
3. **Patch applicability, not repair reasoning, dominated.** 19 of 23 valid
   analyzed cells ended in patch rejection; only four ended with tests as the final
   gate. Across all attempts, 7 of 24 analyzed cells had at least one patch reach
   tests.
4. **One verified success in 23 valid analyzed cells.** It occurred in run 1,
   one-shot, on `return_missing_009`. It did not replicate in run 2.
5. **The evidence condition was rarely activated.** It received a test report in
   two cells. In run 1 the report named the failing test
   (`test_negative_age_rejected`, `Failed: DID NOT RAISE ValueError`), but the
   model's retry was a no-op (`"raise ValueError"` → `"raise ValueError"`). In
   run 2 the report contained only `collection failure`, with no traceback, and
   the retry was a hallucinated `def validate(self, data)`.
6. **No regressions and no protected-asset modifications** were recorded in any
   cell.
7. **The model is not deterministic across runs**, despite `temperature=0` and
   `seed=0`. The same one-shot prompt succeeded in run 1 and failed in run 2. In
   run 1, different conditions produced different first attempts for the same task
   even though the initial prompt is identical.

### Examples of genuine model failures

- `return_missing_009` (blind/evidence, run 1): three overlapping edits. The first
  replaced `"result or None"`; the third searched for
  `"return result or None"`, which no longer existed after the first edit. The
  atomic applier rejected the set.
- `sorting_records_007`: search string used single quotes around `'name'` while the
  file uses double quotes; exact matching correctly rejected it.
- `validation_csv_016`: search string was regex-escaped
  (`str\\.split\\(\\)`), which does not occur in the file.
- `exception_json_005` (run 2): the first response was a Python code block, not
  the requested JSON; the retry used the placeholder `path/to/edit1.py`.

These are not parser bugs. The `edit_json` applier uses exact substring matching
and is atomic; loosening it would hide real model errors.

### Hypotheses (not established by this pilot)

- The 3B model's output-format compliance is the binding constraint. Until patches
  apply reliably, the evidence-guided treatment cannot be evaluated fairly.
- The collection-failure evidence is too thin: `message: collection failure` with
  no traceback gives the model nothing to diagnose. Including the pytest
  collection error would strengthen the treatment.
- The `tmp_path` slowdown is likely memory pressure and/or antivirus/OneDrive
  interaction with the resident model; it needs a controlled measurement.
- A uniform patch-construction phase, or a model that reliably emits applicable
  `edit_json`, would make the strategy comparison informative.

---

## 8. Interpretation

The execution demonstrates that the harness records real model behavior
faithfully: malformed patches, overlapping edits, timeouts, collection errors, and
one genuine verified fix are all persisted with raw output and timing.

It does **not** demonstrate that one strategy is better. The dominant failure mode
occurred before the test suite ran, so most cells compared patch-format compliance,
not repair behavior. The evidence condition was delivered only twice, and both
retries failed. The one-shot success did not replicate across runs. At this sample
size, and with this model, any ranking of the strategies would be noise.

**No statistical-significance claim is made.** The automatic summary's paired
tests are not interpreted; the analyzed sample is 4 tasks, repeated twice, and the
cells are not independent.

---

## 9. Limitations

- One model, one machine, CPU-only, five synthetic tasks, one trial per cell.
- `exception_json_005` was excluded after measurement because its `tmp_path` suite
  became pathologically slow with the model resident. The exclusion is post hoc
  and is reported explicitly.
- Infrastructure timeouts were excluded from valid counts, but they reduce the
  balanced sample: blind retry has 7 valid analyzed cells, versus 8 for the other
  conditions.
- The model is nondeterministic across runs; a single trial is not a stable
  estimate of its behavior.
- `edit_json` exact matching is strict. This is deliberate, but it means the pilot
  measures format compliance as much as repair quality.
- The evidence report for collection failures lacks the underlying traceback.
- The benchmark is synthetic, not production incidents.
- Process isolation is resource/scope control, not a security sandbox.

---

## 10. Smallest justified correction before a real comparison

1. **Keep `exception_json_005` out of the comparison** on this machine, or run it
   only after resolving the `tmp_path` slowdown. Do not count its timeouts as
   strategy failures.
2. **Make patch applicability a separate, uniform phase.** All conditions should
   receive the same format/scope repair opportunities until a patch reaches the
   test suite; only then should the evidence treatment begin. Otherwise blind and
   evidence are often identical, and the experiment measures JSON compliance.
   Alternatively, use a model that reliably emits applicable `edit_json`.
3. **Include the actual pytest collection error/traceback** in the evidence
   report. The current `collection failure` message is not actionable.
4. Keep the applier strict. Do not normalize quotes or ignore overlapping edits to
   rescue bad patches.
5. For a real study, use multiple seeds/runs, a paired or blocked design, and
   report **patch-application rate** alongside verified success. Pre-register the
   sample size and do not interpret significance at pilot scale.

These are proposals. No task, test, scoring rule, or success criterion was changed
for this pilot.

---

## 11. Reproduction

```powershell
# 1. Audit task suitability
python scripts/audit_pilot_tasks.py

# 2. Hydrate OneDrive files and verify baselines
python scripts/preflight_pilot.py --config config/pilot_ollama.yaml

# 3. Verify the local model
python -m verifyloop provider-check --config config/pilot_ollama.yaml

# 4. Run one trial of all five tasks x three conditions
python -m verifyloop run --config config/pilot_ollama.yaml

# 5. Re-analyze the preserved exports (descriptive counts only)
python scripts/analyze_pilot.py --exclude-task exception_json_005 `
  docs/pilot/run-20261020-034833-5bcb12.results.jsonl `
  docs/pilot/run-20261020-090734-fbc80c.results.jsonl

# 6. Verify the code and benchmark
python -m pytest -q
python scripts/validate_benchmark.py
```

The model is nondeterministic, so a new run will not reproduce the exact patches.
The exports below are the authoritative record of these runs.

---

## 12. Artifacts

| File | Contents |
|---|---|
| `docs/pilot/run-20261020-034833-5bcb12.results.csv` | Run 1 flat results |
| `docs/pilot/run-20261020-034833-5bcb12.results.jsonl` | Run 1 full records, attempts, raw outputs |
| `docs/pilot/run-20261020-034833-5bcb12.summary.json` | Run 1 automatic summary |
| `docs/pilot/run-20261020-034833-5bcb12.manifest.json` | Run 1 reproducibility manifest |
| `docs/pilot/run-20261020-090734-fbc80c.results.csv` | Run 2 flat results |
| `docs/pilot/run-20261020-090734-fbc80c.results.jsonl` | Run 2 full records, attempts, raw outputs |
| `docs/pilot/run-20261020-090734-fbc80c.summary.json` | Run 2 automatic summary |
| `docs/pilot/run-20261020-090734-fbc80c.manifest.json` | Run 2 reproducibility manifest |
| `docs/pilot/analysis.md` | Generated descriptive tables |
| `config/pilot_ollama.yaml` | Frozen pilot configuration |
| `scripts/audit_pilot_tasks.py` | Task/test audit |
| `scripts/preflight_pilot.py` | Hydration and baseline preflight |
| `scripts/analyze_pilot.py` | JSONL analysis |

The earlier single-task integration check remains documented in
[`docs/ollama_integration.md`](../ollama_integration.md). Local console logs and the
SQLite database remain under the gitignored `outputs/` directory.
