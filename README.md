# VerifyLoop

**Evidence-guided test-and-repair loops for small coding agents.**

VerifyLoop is a research-grade prototype for asking a narrow question:

> When a small language model writes a failing patch, does giving it structured
> test evidence on the next attempt improve verified bug-fixing compared with
> retrying blindly or making a single attempt?

It is built to make that comparison *fair and auditable*: every condition uses the
same task snapshot, prompt envelope, patch rules, budgets, and independent hidden
evaluation.

---

## Status

| Component | State |
|---|---|
| Repair engine, state machine, budgets | Implemented and tested |
| Three conditions + feedback ablation | Implemented and tested |
| 16-task synthetic benchmark + validation gate | Implemented and validated |
| Deterministic `mock` provider | Working (offline) |
| Native Ollama provider | Working; exercised end-to-end with `llama3.2:3b` |
| Real-model pilot | Completed; **the 3B model did not solve the pilot task** |
| Streamlit dashboard | **Not implemented yet** |

The full local suite currently passes: **164 tests** (unit, security, benchmark,
integration), measured on 2026-10-20.

Mock-provider runs are pipeline demonstrations. They are **never** evidence about
real-model behaviour. The real pilot and its raw outputs are documented in
[`docs/ollama_integration.md`](docs/ollama_integration.md).

---

## Quick start (offline, no model required)

Requires Python 3.10+ and Git.

```powershell
git clone https://github.com/chizyy7/verifyloop.git
cd verifyloop

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

verifyloop doctor
verifyloop validate-bench
verifyloop smoke-test
python -m pytest tests -q
```

`verifyloop smoke-test` runs the complete pipeline with the deterministic mock
provider: baseline reproduction → patch generation → parse/validate/apply → tests →
feedback → retry → independent evaluation.

A mock experiment can be run explicitly (the CLI refuses mock without `--mock`):

```powershell
verifyloop run --config config/default.yaml --mock `
  --task-ids boundary_paginate_001 --strategies oneshot --trials 1
```

---

## Local model with Ollama

Verified configuration:

- Provider: `ollama`
- Base URL: `http://localhost:11434`
- Model: `llama3.2:3b` (Q4_K_M, ~2 GB; suitable for a 16 GB CPU-only laptop)
- Authentication: none

```powershell
ollama pull llama3.2:3b
```

### 1. Check the connection

```powershell
verifyloop provider-check --config config/local_ollama.yaml
```

This checks four things, not just that the port is open:

1. the Ollama API is reachable,
2. the configured model is installed,
3. a small generation request succeeds,
4. the response parses into non-empty text.

Exit codes: `0` pass, `1` check failed, `2` configuration error. The command gives
targeted hints for a stopped server, a missing model, a timeout, or a model that
does not fit in RAM. It never downloads models automatically.

The same check can be driven purely by environment variables:

```powershell
$env:MODEL_PROVIDER="ollama"
$env:MODEL_NAME="llama3.2:3b"
$env:MODEL_BASE_URL="http://localhost:11434"
verifyloop provider-check
```

### 2. Run a real pilot

```powershell
verifyloop run --config config/local_ollama.yaml `
  --task-ids boundary_paginate_001 --strategies oneshot --trials 1 --max-attempts 1
```

The local config uses `edit_json` (search/replace edits) because the pilot showed
that `llama3.2:3b` produced malformed unified diffs while its JSON edits parsed and
applied. Every run manifest records the resolved provider, model, patch format,
budgets, and benchmark version.

To exercise the evidence-guided repair loop:

```powershell
verifyloop run --config config/local_ollama.yaml `
  --task-ids boundary_paginate_001 --strategies evidence_guided `
  --trials 1 --max-attempts 2
```

---

## Conditions

All conditions share the same controller, prompts, budgets, patch validation, and
final evaluation. Only the *information content of the retry prompt* differs.

| Condition | Behaviour |
|---|---|
| `oneshot` | One patch attempt. No feedback, no retry. |
| `blind_retry` | Up to N attempts. Retry says only that the previous attempt failed. |
| `evidence_guided` | Up to N attempts. Retry includes per-test statuses, clipped failure messages, traceback excerpts, regressions, changed files, and remaining budget. |
| `concise_feedback` | Ablation: retry receives pass/fail test names, but no messages or tracebacks. |

Hidden evaluation results are never included in any prompt.

---

## Benchmark

`benchmarks/synthetic/v1` contains **16 synthetic Python repair tasks** across seven
categories:

- `boundary_condition`
- `input_validation`
- `exception_handling`
- `sorting_filtering`
- `return_value`
- `multi_function`
- `multi_file`

Each task contains a broken repository, a visible feedback suite, hidden evaluation
tests, and a reference fix. The benchmark is generated from a single source of truth
(`scripts/build_benchmark.py`) and gated by `scripts/validate_benchmark.py`, which
checks that:

- the baseline fails,
- the reference fix applies,
- visible tests pass after the fix,
- hidden evaluation tests pass after the fix,
- no hidden test or reference content leaks into the prompt context.

```powershell
verifyloop list-tasks
verifyloop validate-bench
```

---

## What the engine guarantees

- **Pristine snapshots.** Every attempt starts from a clean task snapshot; patches
  are never accumulated across retries.
- **Validation before application.** Path traversal, absolute/UNC paths, protected
  paths, deletions, size limits, and file-count limits are checked first.
- **Ambiguity is rejected.** The tolerant diff applier relocates hunks by context
  but refuses to guess when the context is ambiguous.
- **Tests are the source of truth.** JUnit XML is parsed directly; zero collected
  tests is never treated as success.
- **Independent final evaluation.** The final candidate is replayed onto a fresh
  workspace, and hidden tests run where the model never sees them.
- **Full failure accounting.** Rejections, assertion failures, timeouts, model
  errors, budget exhaustion, and regressions are all persisted, including the exact
  model text (bounded).
- **No secrets in config or logs.** API keys are resolved from environment-variable
  names and never serialized; `.env` is gitignored.

Process and temporary-directory isolation is scope and resource control, **not a
security sandbox**.

---

## CLI

| Command | Purpose |
|---|---|
| `verifyloop doctor` | Inspect runtime, benchmark, storage, and provider health |
| `verifyloop provider-check` | Verify reachability, model presence, generation, and parsing |
| `verifyloop list-tasks` | List benchmark tasks (`--json` for machine output) |
| `verifyloop validate-bench` | Run the full benchmark contract check |
| `verifyloop smoke-test` | Offline end-to-end pipeline test with the mock provider |
| `verifyloop run` | Run strategies × tasks × trials under one config |
| `verifyloop export` | Export persisted results to JSONL/CSV/summary |
| `verifyloop report` | Render a descriptive results report |
| `verifyloop ui` | Dashboard entry point (not implemented yet) |

`python -m verifyloop ...` works identically to the `verifyloop` console script.

---

## Results so far

Pilot task: `boundary_paginate_001` (single-file off-by-one defect).
Model: `llama3.2:3b` via Ollama, CPU-only.

| Condition | Format | Attempts | Outcome |
|---|---|---:|---|
| One-shot | `diff` | 1 | `patch_rejected` — hunk declared 7 old lines but contained 11 |
| One-shot | `edit_json` | 1 | `failed_tests` — patch applied, assertion failed |
| Evidence-guided | `edit_json` | 2 | `patch_rejected` — retry edit used `search: "2"`, not found |

**Interpretation:** the integration and repair loop work end-to-end, and failures
are recorded faithfully. The model did **not** solve the task, and no statistical
claim is made from these runs. At this model size, `edit_json` was more reliable than
unified diffs (1/1 parsed vs 0/2). Full details, timings, and raw outputs are in
[`docs/ollama_integration.md`](docs/ollama_integration.md).

---

## Repository layout

```text
verifyloop/
├── benchmarks/synthetic/v1/      16 tasks: repo, tests, eval_tests, reference fix
├── config/
│   ├── default.yaml              offline mock configuration
│   └── local_ollama.yaml         llama3.2:3b pilot configuration
├── docs/
│   ├── ollama_integration.md     commands, measurements, raw outputs, limitations
│   └── phase0_environment_report.md
├── scripts/
│   ├── build_benchmark.py        single source of truth for the corpus
│   ├── validate_benchmark.py     benchmark contract gate
│   ├── run_smoke_test.py         offline end-to-end proof
│   └── probe_provider.py         thin wrapper over the diagnostics
├── src/verifyloop/
│   ├── benchmark/                manifest loading + integrity checks
│   ├── execution/                allowlisted runner, JUnit parser, policies, workspace
│   ├── patching/                 diff/edit_json parser, validator, tolerant applier
│   ├── feedback/                 evidence analyzer + prompt formatter
│   ├── strategies/               oneshot, blind_retry, evidence_guided, ablation
│   ├── model_providers/          base, mock, Ollama, OpenAI-compatible, diagnostics
│   ├── evaluation/               experiment runner + metrics
│   ├── storage/                  SQLite persistence + JSONL/CSV exports
│   ├── reporting/                results tables
│   ├── controller.py             repair loop, budgets, independent evaluation
│   └── cli.py                    command-line interface
└── tests/                        unit, security, benchmark, integration
```

---

## Development

```powershell
pip install -e ".[dev]"
python -m pytest tests/unit -q          # fast suite (~15 s)
python -m pytest tests -q               # full suite, including subprocess integration
```

Optional extras:

```powershell
pip install -e ".[ui]"         # streamlit, pandas
pip install -e ".[analysis]"   # matplotlib, numpy, scipy
```

The repository intentionally ignores `outputs/`, `*.log`, databases, and caches.
Pilot evidence is summarised and linked from the documentation rather than committed
as generated runtime data.

---

## Limitations

- The benchmark is synthetic, not production incidents.
- The pilot uses one task, one trial, and one model; no significance is claimed.
- Inference is CPU-only on a 16 GB laptop. The 8B model could not allocate its
  model-load buffer; the 3B model was used instead.
- Process isolation is not a security sandbox.
- The dashboard is not implemented.
- Token counts use provider-reported usage when available and a character estimate
  otherwise; the estimator is recorded per attempt.

---

## License

MIT. See [`LICENSE`](LICENSE).
