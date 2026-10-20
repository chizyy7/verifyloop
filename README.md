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
| Real-model pilot | Two-run, five-task feasibility pilot completed; **1 verified success in 23 valid analyzed cells; the evidence contrast was not reliably exercised** |
| Streamlit dashboard | **Not implemented yet** |

The full local suite currently passes: **165 tests** (unit, security, benchmark,
integration), measured on 2026-10-20.

Mock-provider runs are pipeline demonstrations. They are **never** evidence about
real-model behaviour. The five-task pilot and its raw exports are documented in
[`docs/pilot/pilot_report.md`](docs/pilot/pilot_report.md); the earlier single-task
integration check is in [`docs/ollama_integration.md`](docs/ollama_integration.md).

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

### 3. Reproduce the five-task feasibility pilot

```powershell
python scripts/preflight_pilot.py --config config/pilot_ollama.yaml
python -m verifyloop provider-check --config config/pilot_ollama.yaml
python -m verifyloop run --config config/pilot_ollama.yaml
```

The preflight hydrates OneDrive placeholders and confirms every selected baseline
fails. The run is sequential and uses the frozen budgets in
`config/pilot_ollama.yaml`. Results are analyzed with `scripts/analyze_pilot.py`;
see [`docs/pilot/pilot_report.md`](docs/pilot/pilot_report.md).

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

### Five-task pilot (2026-10-20)

Model: `llama3.2:3b` via Ollama, CPU-only. Five tasks were selected by an audit
(single-file, small, hidden tests implied by the specification). Four are analyzed;
`exception_json_005` was excluded after its `tmp_path` suite took 97–120 s with the
model resident (2–5 s otherwise), making its timing and feasibility non-comparable.
Two sequential runs are preserved; they are not independent trials.

All recorded cells (including the excluded task):

| Run | Verified | Failed tests | Patch rejected | Infrastructure error |
|---|---:|---:|---:|---:|
| Run 1 | 1 | 2 | 8 | 4 |
| Run 2 | 0 | 1 | 13 | 1 |
| **Total** | **1** | **3** | **21** | **5** |

Analyzed cells (four tasks, infrastructure errors excluded from valid counts):

| Condition | Valid cells | Verified | Failed tests | Patch rejected | Mean attempts | Mean wall s | Mean tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| `oneshot` | 8 | 1 | 2 | 5 | 1.00 | 42.0 | 487 |
| `blind_retry` | 7 | 0 | 0 | 7 | 2.00 | 45.8 | 804 |
| `evidence_guided` | 8 | 0 | 1 | 7 | 2.00 | 40.6 | 781 |

**Key finding:** 19 of 23 valid analyzed cells ended in patch rejection before the
test suite could judge them; only four ended with tests as the final gate. Across all
attempts, 7 of 24 analyzed cells had at least one patch reach tests. The evidence
condition received a structured test report in just two cells (both
`validation_age_003`), and both retries failed. The single verified success (run 1,
one-shot, `return_missing_009`) did not replicate in run 2. The model is
nondeterministic despite `temperature=0` and `seed=0`.

**No strategy is claimed superior, and no statistical significance is claimed.**
The evidence contrast was not exercised often enough to support a comparison; the
dominant failure mode was patch applicability. Full counts, timings, failure
categories, raw examples, limitations, and reproduction commands are in
[`docs/pilot/pilot_report.md`](docs/pilot/pilot_report.md). Generated tables are in
[`docs/pilot/analysis.md`](docs/pilot/analysis.md); the CSV/JSONL exports and run
manifests are under [`docs/pilot/`](docs/pilot/).

### Earlier integration check (single task)

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
│   ├── local_ollama.yaml         earlier single-task Ollama configuration
│   └── pilot_ollama.yaml         frozen five-task pilot configuration
├── docs/
│   ├── ollama_integration.md     earlier integration check and raw outputs
│   ├── phase0_environment_report.md
│   └── pilot/                    pilot report, analysis, CSV/JSONL exports, manifests
├── scripts/
│   ├── build_benchmark.py        single source of truth for the corpus
│   ├── validate_benchmark.py     benchmark contract gate
│   ├── run_smoke_test.py         offline end-to-end proof
│   ├── probe_provider.py         thin wrapper over the diagnostics
│   ├── audit_pilot_tasks.py      task/test suitability audit
│   ├── preflight_pilot.py        OneDrive hydration + baseline preflight
│   └── analyze_pilot.py          descriptive analysis of run JSONL
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

The repository ignores `outputs/`, `*.log`, databases, and caches. Curated pilot
CSV/JSONL exports, summaries, and manifests are committed under `docs/pilot/`;
raw console logs and the SQLite database stay local.

---

## Limitations

- The benchmark is synthetic, not production incidents.
- The feasibility pilot analyzes four tasks over two sequential runs with one
  model; cells are not independent and no significance is claimed. A fifth task
  (`exception_json_005`) was excluded after a measured `tmp_path` slowdown.
- Most analyzed patches were rejected before tests, so the evidence-guided
  contrast was rarely delivered; this pilot cannot rank the strategies.
- The 3B model was nondeterministic across runs despite a fixed seed, so single
  trials are unstable.
- Inference is CPU-only on a 16 GB laptop. The 8B model could not allocate its
  model-load buffer; the 3B model was used instead.
- Process isolation is not a security sandbox.
- The dashboard is not implemented.
- Token counts are Ollama-reported `prompt_eval_count`/`eval_count` for these
  runs; the controller falls back to a character estimate only when a provider
  omits usage.

---

## License

MIT. See [`LICENSE`](LICENSE).
