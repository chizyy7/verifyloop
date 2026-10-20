# VerifyLoop preflight protocol proposal

**Status:** frozen for the patch-format preflight on 2026-10-20. The preflight has not
yet been run at the time this protocol was written. Results belong in
[`preflight_report.md`](preflight_report.md), not here.

**Post-run note (2026-10-20):** the preflight was executed after this protocol was
frozen. The stop-rule decision and actual outputs are in
[`preflight_report.md`](preflight_report.md). This document is left in its
pre-registered form.

**Purpose:** decide whether a later one-shot vs blind-retry vs evidence-guided
comparison has enough test reachability to be informative. This is an experimental
validity step, not a search for a winning strategy.

**Preserved prior work:** the five-task pilot and its artifacts remain unchanged:

- `config/pilot_ollama.yaml`
- `docs/pilot/pilot_report.md`
- `docs/pilot/analysis.md`
- `docs/pilot/*.csv`, `docs/pilot/*.jsonl`, `docs/pilot/*.summary.json`,
  `docs/pilot/*.manifest.json`
- pilot commits `5553a4a`, `e28094a`, and `48c5f63`

New runs use new run IDs and write to `docs/preflight/` and `outputs/preflight/`.
Nothing in this protocol overwrites or reinterprets the pilot.

---

## 1. Pipeline audit: where a condition can fail before test feedback

The controller is shared by all conditions. The retry-prompt information is the
intended difference; the mechanics below are not.

| Stage | Possible failure | Current signal before this change | New per-attempt diagnostic |
|---|---|---|---|
| Model response | provider error, timeout, empty/truncated response | `model_error`, raw output | `model_response_received`, `failure_stage=model_response` |
| Patch format | prose instead of JSON, malformed JSON, wrong root shape, missing keys, empty search, unsupported format | `patch_rejected`, `patch_format` | `patch_format_parsed=false`, `failure_stage=patch_format` |
| Applicability validation | protected path, traversal, absolute path, oversized patch, too many files, missing file | validation reason | `applicability_checked`, `applicability_validated`, `failure_stage=patch_validation` |
| Application | non-unique search, missing search text, overlapping edits, no-op patch, ambiguous diff context | rejection reason, `applied=false` | `patch_applied`, `failure_stage=patch_application` |
| Test collection | import error, syntax/indentation error, no tests collected | often only “collection failure” in JUnit | `tests_collected=false`, `test_outcome=collection_error`, bounded `collection_error_excerpt` |
| Test execution | harness launch error, timeout, partial output | `infrastructure_error`, `timed_out` | `tests_executed=false`, `failure_stage=test_execution` |
| Test result | assertions or errors after tests ran | `failed_tests` | `tests_failed=true`, `test_outcome=failed`, `failure_stage=test_result` |
| Evidence delivery | retry prompt was generated but no structured evidence reached the next attempt | `feedback_reports` only | `evidence_delivered`, `evidence_kind`, prompt SHA-256 and character count |

This distinction matters: “patch rejected” previously combined format, scope, and
application failures, while “collection failure” could hide the actual syntax or
import error. Neither is a test of the repair strategy.

### Why the pilot evidence contrast was weak

In the preserved pilot, 19 of 23 valid analyzed cells ended as `patch_rejected`
before tests ran. Only four valid cells used tests as the final gate. Structured
evidence reached a retry in only two cells, both `validation_age_003`, and both
retries failed. A strategy comparison before fixing this would mostly measure patch
formatting and application, not evidence-guided repair.

---

## 2. Conditions for a later comparison (not launched by this preflight)

| Condition | Attempts | Information on retry |
|---|---:|---|
| `oneshot` | 1 | None. The condition stops after the first attempt. |
| `blind_retry` | up to N | Only that the previous attempt failed. No test names, messages, collection error, or regression information. |
| `evidence_guided` | up to N | Structured visible-test evidence: statuses, failing test names, clipped messages, traceback excerpts, collection-error excerpt, regressions, changed files, remaining budget. |

### Shared mechanics

All conditions must use:

- the same task snapshot, task description, expected behavior, and repository context;
- the same initial prompt and the same patch-format instructions;
- the same parser, validator, applier, protected-path policy, and patch-size limits;
- the same visible feedback suite and hidden evaluation suite;
- the same model, provider, temperature, seed, request timeout, token ceiling,
  attempt ceiling where the condition permits retries, and wall-clock ceiling;
- the same final independent evaluation on a fresh workspace;
- the same handling of provider errors, collection failures, and infrastructure
  errors.

### Unavoidable differences

- `oneshot` has no retry by definition. Its attempt budget is one effective attempt
  even if the configured ceiling is larger.
- Retrying conditions receive a retry prompt after a rejected patch. Both are told
  that the patch was rejected and why; this is necessary for progress and is not
  test evidence. `blind_retry` receives no test-derived content.
- `evidence_guided` receives test-derived content by design. The `concise_feedback`
  ablation remains available but is outside the three-condition primary comparison.
- A provider error is not retried in `oneshot`; it may be retried in the other
  conditions if budget remains. This preserves the meaning of “one shot” and is
  recorded per attempt.

---

## 3. Patch representation policy

The preserved pilot used `edit_json` after unified diffs produced malformed hunk
counts. The pilot still showed frequent edit_json failures: malformed JSON, missing
files, hallucinated functions, non-unique or absent search text, and overlapping
edits.

The preflight compares two representations under the same one-shot condition:

1. **`edit_json`** — existing format: `{"edits": [{"file", "search", "replace"}]}`.
2. **`edit_json_single`** — new strict format: exactly one object with exactly
   `file`, `search`, and `replace`; no list, no extra keys, no no-op replacement.

`edit_json_single` keeps the existing applier and validation rules. It removes
multi-edit overlap and ambiguous list-shape failure modes, but it may be too
restrictive for tasks requiring several independent edits. That is an empirical
question for the preflight, not an assumption.

No format will be changed midway through a strategy comparison. The format is
selected before the comparison starts and recorded in the run manifest.

---

## 4. Preflight design

**Frozen configuration:** `config/preflight_patch_formats.yaml`

- Model: `llama3.2:3b` via Ollama, CPU-only.
- Provider settings: `temperature=0.0`, `seed=0`, 120 s request timeout,
  700 max output tokens.
- Tasks: `return_missing_009`, `sorting_records_007`, `validation_age_003`.
  These are audited tasks from the previous pilot.
- Excluded: `exception_json_005` because its `tmp_path` suite showed a 97–120 s
  slowdown on this machine, making timing non-comparable.
- One condition only: `oneshot`.
- One attempt per task, one trial.
- Budgets: 1 model call, 12,000 total tokens, 300 s wall clock, 120 s test timeout.
- Formats: `edit_json` and `edit_json_single`.
- Each format is a separate run with a new run ID.

The preflight is intentionally not a strategy comparison. It measures:

- whether the model response arrived;
- whether the format parsed;
- whether applicability validation passed;
- whether the patch applied;
- whether tests were collected;
- whether tests executed;
- whether the patch passed or failed tests;
- whether a collection error excerpt was captured.

---

## 5. Pre-declared stop rule

A format is **preflight-ready** only if, across the three tasks:

1. at least two patches apply;
2. at least two attempts execute a non-empty test suite;
3. there are no infrastructure errors.

The same rule is applied to both formats. If no format meets the rule, the strategy
comparison is not launched. If one or both meet it, the protocol is frozen and the
representation is selected before any comparison. Selection is based on format
validity, applicability, and test reachability only; it must not be based on which
format makes a particular strategy look better.

The preflight does not establish statistical significance, strategy superiority, or
generality beyond these three tasks.

---

## 6. Evidence contract for collection failures

When pytest fails during collection, the controller must send the next attempt a
bounded, redacted excerpt containing the useful error, for example:

```text
==================================== ERRORS ====================================
____________________ ERROR collecting tests/test_validation.py ____________________
...
E   IndentationError: unexpected indent
...
```

Rules:

- derive evidence only from the visible feedback suite, never from hidden evaluation
  tests;
- capture the pytest `ERRORS` section around `ERROR collecting` / collection errors;
- stop before the short test summary and cap the excerpt (2,400 characters, 40 lines,
  400 characters per line);
- redact environment values whose names look secret-bearing and common credential
  shapes;
- do not include the full console output or unrelated environment data;
- record whether the excerpt was captured and whether evidence was delivered to the
  next attempt.

---

## 7. Main comparison gate (not part of this preflight)

The main comparison remains blocked until:

- the preflight report shows a format meeting the stop rule;
- the full test suite, benchmark validation, and mock smoke test pass;
- the protocol is frozen with the selected format, task list, attempt budget, model
  settings, timeouts, and analysis plan;
- the analysis plan reports patch-parse, application, test-reachability, and verified
  success separately, with numerators and denominators.

If those conditions are not met, the next step is to improve the pipeline or the
benchmark tasks, not to run a larger experiment.

### Conditional comparison parameters (not run)

If the preflight passes, the smallest defensible follow-up is:

| Parameter | Proposed value |
|---|---|
| Representation | `edit_json_single`, frozen before the run |
| Tasks | the three preflighted tasks only: `return_missing_009`, `sorting_records_007`, `validation_age_003` |
| Conditions | `oneshot`, `blind_retry`, `evidence_guided` |
| Trials | 2 per task/condition (descriptive replication, not power) |
| Effective attempts | 1 for `oneshot`; 2 for each retrying condition |
| Model | `llama3.2:3b`, temperature 0.0, seed 0, 700 output tokens |
| Request / test timeout | 120 s / 120 s |
| Budgets | `max_attempts=2`, `max_model_calls=3`, `max_total_tokens=30000`, `max_wall_clock_seconds=300`, `max_patch_bytes=24000`, `max_output_chars=6000` |
| Task order | fixed manifest order with the config seed recorded |
| Analysis | stage and outcome counts with numerators/denominators; no p-values or superiority claim |

`exception_json_005` remains excluded from timing-sensitive work. The other previously
excluded tasks remain excluded for hidden-test alignment reasons. No task, visible
test, hidden test, or scoring rule is changed for the comparison.

This table is a proposal, not an executed run. The comparison must receive a new,
frozen config and new run IDs after the preflight decision is reviewed.

---

## 8. Reproduction commands

```powershell
# Hygiene and baseline checks for the preflight tasks
python scripts/preflight_pilot.py --config config/preflight_patch_formats.yaml
python -m verifyloop provider-check --config config/preflight_patch_formats.yaml

# Format / reachability preflight (new run IDs, new artifacts)
python scripts/preflight_patch_formats.py --config config/preflight_patch_formats.yaml

# Evidence and regression suite
python -m pytest tests -q
python -m verifyloop validate-bench
python -m verifyloop smoke-test
```

The preflight writes its combined summary to
`outputs/preflight/preflight_summary.json` and per-run JSONL/CSV/summary/manifest
files under `outputs/preflight/`. Curated copies for the report will be placed under
`docs/preflight/` only after the run.

---

## 9. Limitations to carry forward

- Three tasks, one model, one trial per task/format: descriptive only.
- The benchmark is synthetic and small.
- Inference is CPU-only; timing is machine-specific.
- The model was nondeterministic in the prior pilot despite a fixed seed.
- `edit_json_single` may be too restrictive for multi-edit tasks.
- The format preflight cannot tell us whether evidence-guided repair helps; it only
  tells us whether a later comparison would reach tests often enough to be worth
  running.
- Process isolation is resource/scope control, not a security sandbox.
