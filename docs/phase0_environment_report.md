# Phase 0 — Environment, Feasibility, Architecture, and Protocol

Status: **complete** (2026-10-19)
Author: VerifyLoop build session
Scope: pre-implementation inspection. No experimental results exist yet.

---

## 1. Environment report

### 1.1 Host

| Item | Observed value | Implication |
|---|---|---|
| OS | Windows 10.0.26200 (Windows 11 build), AMD64 | Subprocess/PowerShell paths must be tested explicitly |
| CPU | 8 logical processors | CPU-only inference is the realistic constraint |
| RAM | 16,407,719,936 bytes (15.3 GiB) | Fits a 4B-class Q4 model with headroom; 8B is tight but workable |
| GPU | AMD Radeon integrated graphics, 512 MB reported adapter RAM, no `nvidia-smi` | **No usable CUDA GPU.** Do not plan GPU inference or large-batch experiments |
| Disk (C:) | 31.9 GB free of 475 GB | Enough for the repo, SQLite, outputs. Not enough for many model weights |
| Python | 3.10.11 at `C:\Users\chizy\AppData\Local\Programs\Python\Python310\python.exe` | Target `>=3.10`. Avoid 3.11+/3.12-only syntax (`Self`, `tomllib`, `X | Y` in `isinstance`) |
| pip | 23.0.1 | Editable install with setuptools works |
| Git | 2.56.0.windows.2 | Available for versioning, worktree snapshots, tree diffs |
| Node | v24.13.0 | Not required by this project |
| Docker | CLI not on PATH (Docker Desktop shortcut present) | **Do not depend on containers.** Isolation is documented as best-effort, not a security sandbox |

### 1.2 Python packages already present

`pydantic 2.13.4`, `pytest 9.1.1`, `streamlit 1.62.0`, `matplotlib 3.10.9`,
`pandas 2.3.3`, `numpy 2.2.6`, `scipy 1.15.3`, `pyyaml`, `httpx`, `jinja2`,
`requests`, `rich`. No installation is strictly required for the MVP.

### 1.3 Model availability (verified by probe, not assumed)

| Provider | Status |
|---|---|
| Ollama daemon | **Running** at `http://localhost:11434` |
| `llama3.1:8b` (Q4_K_M, 4.9 GB) | **Installed and usable** — the practical small-model workhorse for this machine |
| `nomic-embed-text` | Installed (embedding only, irrelevant here) |
| LM Studio | Not running / not installed |
| Anthropic API key | Present in the environment (`ANTHROPIC_API_KEY=SET`) |
| OpenAI / Google / Groq / OpenRouter keys | Not set |
| `MODEL_PROVIDER` / `MODEL_NAME` / `MODEL_BASE_URL` | Not set |

**Important honesty note on model identity.** The competition track is described as a
"Google Gemma 4 Developer Agent Paper Track." No verifiable Gemma 4 technical report
was retrievable from arXiv during this build (only Gemma 2, arXiv:2408.00118, and
Gemma 3, arXiv:2503.19786, were found). We therefore do **not** claim to evaluate
Gemma 4. The system is model-agnostic. Two configurations are supported:

- **Primary (offline, reproducible on this laptop):** `llama3.1:8b` via Ollama.
- **Gemma variant (recommended before submission):** any Gemma checkpoint served by
  Ollama (e.g. `gemma3:4b`) or an OpenAI-compatible Gemma endpoint. A ~3 GB pull is
  feasible given 31.9 GB free disk, but was **not** performed during Phase 0.

Whatever model is used must be named exactly in every results table. No result may be
reported as a "Gemma result" unless the model identifier recorded in the run metadata
is a Gemma checkpoint.

### 1.4 Secrets handling

Only variable **names** were inspected. No secret value was printed, logged, or written.
Provider configuration stores the *name* of an environment variable, never the key.
`.env` is git-ignored; `.env.example` contains placeholders only.

---

## 2. Feasibility assessment

| Capability | Feasible now? | Notes |
|---|---|---|
| Full engine, benchmark, evaluator, CLI, dashboard, tests | **Yes** | Pure Python; no network needed |
| Deterministic mock-model end-to-end runs | **Yes** | Required for CI and for grading without spend |
| Real LLM runs (local, CPU) | **Yes, slowly** | 8B Q4 on 8 CPU cores: expect roughly 3–15 s per 300-token completion depending on prompt size. A 16-task × 3-strategy × 3-trial study ≈ 144 runs × up to 4 calls ≈ 400–600 calls. At ~20 s/call this is 2–3.5 hours of generation, plus test time. Feasible overnight; not feasible in a 10-minute demo |
| Remote API runs | **Partially** | Anthropic key exists but the project's provider layer targets OpenAI-compatible endpoints. An Anthropic adapter was **not** implemented (would need a different wire format). Recorded as a limitation, not a silent gap |
| Docker sandboxing | **No** | Documented threat model instead. Benchmark repos are locally generated and trusted |
| SWE-bench Verified | **No** | Needs Linux containers, large repos, heavy dependencies. Explicitly deferred; documented as future work |
| Statistical power | **Limited** | 16 tasks × 3 trials = 48 paired observations. Enough for descriptive comparison and exact McNemar tests, not for narrow CIs. Reported honestly |

---

## 3. Proposed architecture

```
verifyloop/
  config/default.yaml          # declarative experiment configuration
  src/verifyloop/
    config.py                  # pydantic settings, env resolution, redaction
    state_machine.py           # explicit states + legal transitions + event log
    controller.py              # the repair loop (strategy-agnostic)
    model_providers/           # base ABC, ollama, openai-compatible, mock
    benchmark/                 # manifest schema, loader, integrity validation
    patching/                  # extraction, diff/edit parsing, path+size validation, applier
    execution/                 # allowlisted subprocess runner, pytest/JUnit parsing
    feedback/                  # failure classification + structured report rendering
    strategies/                # oneshot, blind_retry, evidence_guided, concise_feedback
    evaluation/                # independent evaluator, metrics, statistics
    storage/                   # SQLite schema + repository + JSONL/CSV export
    reporting/                 # matplotlib figures + markdown tables
    ui/app.py                  # Streamlit dashboard (read-only over persisted data)
    cli.py                     # doctor/list-tasks/smoke-test/run/export/report/ui
  benchmarks/synthetic/v1/     # versioned task corpus
  tests/{unit,integration,security,benchmark}/
  docs/, research/, outputs/
```

### 3.1 Data flow (one attempt)

```
task.json ──► loader ──► pristine snapshot (immutable, read-only by convention)
                              │
                              ▼
                    git-backed workspace  ──► prompt builder (strategy-specific)
                              │                        │
                              │                        ▼
                              │                   model provider
                              │                        │
                              ▼                        ▼
                    patch parser/validator ◄──── raw completion
                              │
                     (reject: path, size, protected asset, malformed)
                              ▼
                        apply to workspace
                              ▼
                 allowlisted pytest run (timeout, capped output)
                              ▼
                  JUnit XML → structured TestReport
                              ▼
             failure classifier ──► feedback (evidence strategy only)
                              ▼
                    budget check → retry or finalize
                              ▼
        independent eval tests on a *fresh copy* of the final candidate
                              ▼
                   SQLite + JSONL + metrics
```

### 3.2 Key design decisions (defaults chosen, not delegated)

1. **Git-backed workspaces.** Each task attempt runs in a temporary copy with a local
   git repo whose first commit is the pristine snapshot. Reset between attempts is
   `git reset --hard` + `git clean -fd`, which cannot silently corrupt state. Git is
   already required for project versioning.
2. **Own unified-diff applier, tolerant of wrong line numbers.** Models frequently emit
   correct hunks with incorrect `@@` offsets. We locate hunks by context with a strict
   uniqueness requirement, then verify the resulting file byte-for-byte against the
   intended edit. `git apply` is *not* trusted as the sole gate because its failure
   modes are opaque to the feedback generator.
3. **Two patch formats.** `diff` (default) and `edit_json` (search/replace blocks).
   Chosen after pilot, recorded in run metadata. Same format for all strategies.
4. **JUnit XML as the test source of truth.** pytest exit codes alone cannot distinguish
   "no tests collected" from "all passed" reliably across plugins; we parse both and
   cross-check.
5. **Hidden tests are never materialized in the agent workspace.** Evaluation runs in a
   separate directory that the model never sees, using the same allowlisted command
   shape.
6. **SQLite (stdlib `sqlite3`)** rather than an ORM. Portable, zero-dependency, easy to
   inspect and export.
7. **Mock provider is first-class**, not an afterthought: every controller path must be
   exercisable offline.

---

## 4. Initial research protocol (pre-registered before any real run)

- **Design:** within-task, within-model paired comparison. Every task is attempted by
  all strategies at the same attempt limit and token budget, in a recorded order.
- **Primary outcome:** verified success — the independent evaluation suite passes
  (exit 0, ≥1 test collected) and no protected asset was modified.
- **Secondary:** regression-free success, visible-test success, attempts used, model
  calls, tokens, wall-clock, patch-application failure rate, failure categories.
- **Strategies:** A one-shot (1 attempt); B blind retry (N attempts, no diagnosis);
  C evidence-guided (N attempts, structured report).
- **Matching:** identical model id, temperature, seed policy, task text, repository
  snapshot, patch rules, test command, attempt cap, and token cap. Blind and evidence
  get the same attempt cap. A secondary matched-*token* analysis is reported.
- **Trials:** ≥3 per task/strategy if time allows; otherwise the reduced power is stated.
- **Exclusions:** infrastructure failures (provider down, harness crash) are excluded
  from the success denominator *and* reported separately. Baseline-invalid tasks are
  excluded by rule, never by post-hoc choice.
- **Statistics:** Wilson intervals for proportions; exact McNemar for paired binary
  outcomes; paired bootstrap for differences; Wilcoxon signed-rank for cost. With n=16
  tasks we report effect sizes and uncertainty, not p-value stars.
- **Freeze rule:** the protocol is frozen after the pilot. Any post-pilot change is
  logged in `docs/research_protocol.md` with rationale.

Hypotheses H1–H4 are recorded in `docs/research_protocol.md` and in
`research/paper_outline.md`, verbatim from the brief.

---

## 5. Prioritized implementation checklist

Legend: `[ ]` todo · `[x]` done · `[~]` partial · `[!]` blocked

**P0 — foundation**
- [x] Environment inspection
- [x] Verify literature identifiers resolve (arXiv API)
- [ ] Repo skeleton, pyproject, config, .gitignore, .env.example
- [ ] Config validation + secret redaction tests
- [ ] State machine + tests

**P1 — end-to-end mock prototype**
- [ ] Manifest schema + loader
- [ ] Patch parser/validator/applier + security tests
- [ ] Execution runner + pytest result parser + timeout/no-tests tests
- [ ] Mock provider
- [ ] Controller (one task, one attempt)
- [ ] Smoke test: buggy → patch → tests → pass

**P2 — benchmark**
- [ ] 16 synthetic tasks, 7 categories
- [ ] Automated benchmark integrity validation (baseline fails, reference passes)
- [ ] Protected-asset enforcement tests

**P3 — strategies**
- [ ] One-shot, blind retry, evidence-guided, concise-feedback
- [ ] Integration scenarios 1–10 from the brief

**P4 — real model**
- [ ] Ollama adapter, connectivity probe, pilot on 2–3 tasks
- [ ] Verify token accounting; document latency on this hardware

**P5 — persistence & analysis**
- [ ] SQLite schema, repository, JSONL/CSV export
- [ ] Metrics, Wilson CI, McNemar, bootstrap
- [ ] Reproducibility manifest per experiment

**P6 — dashboard**
- [ ] Overview, run, task inspector, comparison, history, report pages
- [ ] Empty-state honesty: no fabricated data anywhere

**P7 — pilot & freeze**
- [ ] Pilot, harness bug fixes, protocol freeze note

**P8 — main experiment**
- [ ] Run, persist raw trials, no cherry-picking

**P9 — analysis & paper**
- [ ] Figures/tables from real data, results summary, paper outline filled

**P10 — audit**
- [ ] Full test suite, secret scan, reproducibility walkthrough, demo script

---

## 6. Risk register (most likely to prevent completion)

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | 8B CPU inference too slow for a full 3×16×3 study | High | High | Tiered plan: 8-task pilot → 16-task main; attempt cap 3; cache prompts; allow overnight run; report reduced n if needed |
| R2 | Small model emits malformed diffs, so all strategies score ~0 | High | High | Tolerant applier, `edit_json` fallback format, concise prompt with one worked example, and honest reporting if format failure dominates |
| R3 | Windows subprocess/pytest path quirks (spaces in `OneDrive` path, encoding) | Medium | Medium | Explicit `cwd=`, `PYTHONIOENCODING=utf-8`, UTF-8 file I/O everywhere, integration tests that run real pytest |
| R4 | OneDrive sync locks temp files | Medium | Medium | All workspaces under `%TEMP%\verifyloop`, not OneDrive; documented |
| R5 | Synthetic tasks too easy → ceiling effect, no measurable difference | Medium | High | Include multi-file and interaction bugs; calibrate in pilot; report ceiling honestly |
| R6 | Eval tests leak into agent context | Low | Critical | Separate directories, path allowlist, protected-asset rejection, dedicated security tests |
| R7 | Unbounded model/test usage | Medium | Medium | Hard caps: calls, tokens, attempts, wall-clock, patch size, output size |
| R8 | Statistical overreach from n=16 | High | Medium | Wilson CIs, exact tests, explicit power statement, no causal claims |
| R9 | Gemma-specific track expectations unmet | Medium | Medium | Model-agnostic design; documented Gemma swap procedure; do not mislabel model |
| R10 | Reviewer cannot reproduce | Medium | High | `doctor` command, pinned versions, seed recording, mock smoke test, exact PowerShell instructions |

---

## 7. What can be built and tested without an LLM

Everything except the real-model adapter's live behaviour: configuration, state machine,
benchmark validation, patch parsing/validation/application, subprocess execution and
result parsing, failure classification, feedback rendering, budgets, persistence,
metrics, statistics, exports, plots, dashboard rendering, and the entire controller via
the scripted mock provider. This is the majority of the system and all of its correctness
surface.

---

## 8. Next action

Phase 1: repository skeleton, configuration, state machine, and the first end-to-end
mock run on one synthetic task.
