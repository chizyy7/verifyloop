# Patch-format and test-reachability preflight report

**Date:** 2026-10-20
**Status:** completed; format selection supported for a future protocol, but **no main
strategy comparison was launched**.
**Scope:** stage diagnostics, collection-error evidence, and a three-task comparison
of two patch representations under one one-shot attempt. This is not a test of
whether evidence-guided repair helps.

The pre-declared protocol and stop rule are in
[`protocol_proposal.md`](protocol_proposal.md). They were written before this run.

---

## 1. Setup

| Item | Value |
|---|---|
| Provider / model | Ollama / `llama3.2:3b` |
| Host | Windows 10.0.26200, AMD64, CPU-only |
| Python | 3.10.11 |
| Benchmark | `verifyloop-synthetic` v1 |
| Tasks | `return_missing_009`, `sorting_records_007`, `validation_age_003` |
| Condition | `oneshot` only |
| Attempts / trial | 1 |
| Formats | `edit_json`, `edit_json_single` |
| Temperature / seed | `0.0` / `0` |
| Request timeout | 120 s |
| Test timeout | 120 s |
| Wall-clock budget | 300 s per task |
| Model-call / token budget | 1 call, 12,000 tokens per task |

The format preflight deliberately uses only one condition. A strategy comparison
would confound format validity with retry policy. Both formats use the same tasks,
model settings, initial prompt envelope, validation rules, applier, test commands,
and budgets. The only intended input difference is the requested patch representation.

Frozen config: `config/preflight_patch_formats.yaml`.

---

## 2. Pre-declared stop rule

A format is preflight-ready only if, across the three tasks:

1. at least two patches apply;
2. at least two attempts execute a non-empty test suite;
3. there are no infrastructure errors.

The rule was applied identically to both formats. The preflight did not select a
format based on which one made a particular strategy look better; no strategy was
run.

---

## 3. Results

Final reported runs:

- `edit_json`: `run-20261020-104426-e50202`
- `edit_json_single`: `run-20261020-104552-2bc638`

| Format | Tasks | Response | Parsed | Validated | Applied | Collected | Executed | Verified | Infra |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `edit_json` | 3 | 3 | 3 | 3 | 1 | 0 | 0 | 0 | 0 |
| `edit_json_single` | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 1 | 0 |

`Validated` means applicability validation passed. `Collected` and `Executed` are
stage outcomes, not test counts. `Verified` is a task outcome, not a strategy result.

**Stop-rule decision:** `edit_json` failed (1/3 applied, 0/3 reached tests).
`edit_json_single` passed (3/3 applied, 3/3 reached tests, 0 infrastructure errors).
The preflight therefore supports freezing `edit_json_single` for any future
comparison. It does **not** show that evidence-guided repair is better than blind
retry or one-shot.

### Per-task stage table

| Format | Task | Outcome | Applied | Collected | Executed | Passed | Failed | First failing stage |
|---|---|---|---:|---:|---:|---:|---:|---|
| `edit_json` | `return_missing_009` | `patch_rejected` | no | no | no | no | no | `patch_application` |
| `edit_json` | `sorting_records_007` | `patch_rejected` | no | no | no | no | no | `patch_application` |
| `edit_json` | `validation_age_003` | `failed_tests` | yes | no | no | no | no | `test_collection` |
| `edit_json_single` | `return_missing_009` | `verified_success` | yes | yes | yes | yes | no | — |
| `edit_json_single` | `sorting_records_007` | `failed_tests` | yes | yes | yes | no | yes | `test_result` |
| `edit_json_single` | `validation_age_003` | `failed_tests` | yes | yes | yes | no | yes | `test_result` |

### What failed before tests

- `edit_json` `return_missing_009`: the model emitted three edits. Its first search
  string (`result or None`) did not match the file, and another edit was a no-op.
  The applier correctly rejected the patch atomically. Stage:
  `patch_application`; reason: `search text not found in diffing.py`.
- `edit_json` `sorting_records_007`: the single edit was a no-op whose search text
  (`record[key], record['name']`) did not match. Stage: `patch_application`;
  reason: `search text not found in ranking.py`.
- `edit_json` `validation_age_003`: the patch applied but produced a syntax error.
  Pytest could not collect tests. This is the case the new collection-evidence path
  was added for.
- `edit_json_single` `return_missing_009`: one edit, `return result or None` →
  `return [] if not result else result`; visible and hidden tests passed.
- `edit_json_single` `sorting_records_007`: one edit applied, but changed
  `record[key]` to the literal `record['key']`. Tests executed and failed.
- `edit_json_single` `validation_age_003`: one edit applied (bool rejection only),
  but the negative-age defect remained. Three visible tests passed and one failed.

The important distinction is visible in the table: under `edit_json`, zero attempts
reached test execution, so a strategy comparison would mostly measure patch
applicability. Under `edit_json_single`, all attempts reached tests, so the test
outcome is at least observable.

---

## 4. Collection-error evidence

The `edit_json` `validation_age_003` attempt applied a patch that made the source
invalid. The structured evidence sent to a retry would contain this bounded excerpt:

```text
=================================== ERRORS ====================================
__________________ ERROR collecting tests/test_validation.py __________________
tests\test_validation.py:3: in <module>
    from validation import validate_age
E     File "validation.py", line 9
E       raise ValueError if value > 150 else raise TypeError("age must be between 0 and 150")
E                                            ^^^^^
E   SyntaxError: invalid syntax
```

The excerpt:

- comes only from the visible feedback suite;
- includes the actual exception and the offending source line;
- stops before the short test summary;
- is capped at 2,400 characters, 40 lines, and 400 characters per line;
- removes pytest/site-packages frames and normalizes the absolute temporary path;
- is passed through secret redaction before being stored or sent.

No hidden evaluation output is included. In this one-shot preflight, no retry was
delivered, so `evidence_delivered` is false for every cell by design. The controller
tests exercise the delivery path separately with scripted broken-then-correct
responses.

---

## 5. Timing and tokens

| Format | Total wall s | Generation s | Test s | Total tokens |
|---|---:|---:|---:|---:|
| `edit_json` | 85.6 | 56.5 | 6.2 | 1,540 |
| `edit_json_single` | 67.4 | 30.6 | 13.5 | 1,450 |

These totals include each task's baseline check, one model call, and any feedback or
final evaluation that the outcome allowed. The single-edit format had lower total
wall time in this run, but timing is machine- and load-dependent and is not a
primary criterion.

---

## 6. Verification outputs

Run on the final code state:

```text
python -m pytest tests -q
186 passed in 212.97s (0:03:32)

python -m verifyloop validate-bench
all 16 tasks validated

python -m verifyloop smoke-test
[correct patch, one shot] outcome=verified_success attempts=1 calls=1
[wrong patch then correct] outcome=verified_success attempts=2 calls=2
[always wrong, exhausted] outcome=failed_tests attempts=3 calls=3
```

The preflight hygiene check also passed:

```text
python scripts/preflight_pilot.py --config config/preflight_patch_formats.yaml
hydrating 115 benchmark files under ...\benchmarks\synthetic
hydrated 68.9 KiB
checking 3 task baselines
ok   return_missing_009: 2 passed, 1 failed, 0 errors, 0 skipped (3.3s wall, 1.7s test)
ok   sorting_records_007: 2 passed, 1 failed, 0 errors, 0 skipped (2.8s wall, 1.4s test)
ok   validation_age_003: 3 passed, 1 failed, 0 errors, 0 skipped (3.5s wall, 2.1s test)
preflight passed
```

The provider check passed:

```text
[OK] api_reachable
[OK] model_installed
[OK] generation: completed in 13.14s
[OK] response_parseable
result: PASS
```

---

## 7. Decision and next step

**Decision:** freeze `edit_json_single` as the patch representation for a future
comparison. The preflight stop rule is met for that format, and it removes the
multi-edit/overlap failures that dominated the earlier `edit_json` attempts.

**What this does not decide:** which repair strategy is better. The preflight ran
one-shot only, with one attempt per task and three tasks total. It also produced one
verified success under `edit_json_single`, which is a single cell, not a strategy
result and not evidence of generality.

**Next step, if the project continues:** freeze a new main-comparison protocol with
`edit_json_single`, the same three conditions, a declared attempt budget, multiple
trials, and a pre-declared analysis plan that reports parse/application/test
reachability separately from verified success. A proposed parameter table is in
[`protocol_proposal.md`](protocol_proposal.md) §7. Do not change the format midway.
The main comparison is **not** launched here.

An earlier local preflight under the same protocol was used to inspect excerpt
quality before the bounded cleanup above. Its outputs remain under
`outputs/preflight/` and `outputs/preflight_v2/`; the tables in this report use only
the final `outputs/preflight_v3/` run. The earlier runs are not counted as
independent trials.

---

## 8. Limitations

- Three tasks, one model, one trial per task/format: descriptive only.
- The benchmark is synthetic, not production incidents.
- CPU-only inference on one machine; timings are not portable.
- The model was nondeterministic in the earlier pilot despite `temperature=0` and
  `seed=0`. Repeating this preflight can change model outputs and token counts.
- `edit_json_single` may be too restrictive for tasks that genuinely need multiple
  independent edits; this preflight does not establish that it generalizes.
- The preflight did not exercise evidence-guided retry. It only established that a
  future comparison can reach the test stage.
- Process isolation is resource/scope control, not a security sandbox.

---

## 9. Reproduction commands

Use a fresh output directory so existing run artifacts are not overwritten:

```powershell
python scripts/preflight_pilot.py --config config/preflight_patch_formats.yaml
python -m verifyloop provider-check --config config/preflight_patch_formats.yaml
python scripts/preflight_patch_formats.py `
  --config config/preflight_patch_formats.yaml `
  --output outputs/preflight_repro

python -m pytest tests -q
python -m verifyloop validate-bench
python -m verifyloop smoke-test
```

Every preflight run receives a new run ID. The script prints a stage table and writes
a combined `preflight_summary.json` plus per-run JSONL/CSV/summary/manifest files.

---

## 10. Preflight artifacts

- `config/preflight_patch_formats.yaml`
- `docs/preflight/protocol_proposal.md`
- `docs/preflight/preflight_summary.json`
- `docs/preflight/run-20261020-104426-e50202.manifest.json`
- `docs/preflight/run-20261020-104426-e50202.results.jsonl`
- `docs/preflight/run-20261020-104426-e50202.results.csv`
- `docs/preflight/run-20261020-104426-e50202.summary.json`
- `docs/preflight/run-20261020-104552-2bc638.manifest.json`
- `docs/preflight/run-20261020-104552-2bc638.results.jsonl`
- `docs/preflight/run-20261020-104552-2bc638.results.csv`
- `docs/preflight/run-20261020-104552-2bc638.summary.json`

The original pilot artifacts under `docs/pilot/` and the frozen pilot config remain
unchanged.
