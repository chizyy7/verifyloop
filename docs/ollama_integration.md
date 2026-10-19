# Local Ollama integration — `llama3.2:3b`

Date: 2026-10-20
Status: **implemented and exercised end-to-end**. The model generated patches, the
patches were parsed, validated, applied, tested, and recorded. The model did **not**
solve the pilot task; that is reported as a negative result, not hidden.

This document covers the local-provider path only. Mock-provider results are
pipeline demonstrations and are never evidence about real-model behaviour.

## 1. Architecture reused

VerifyLoop already had a provider-independent interface:

- `src/verifyloop/model_providers/base.py` — `ModelProvider`, `Completion`,
  `ProviderError` and subclasses.
- `src/verifyloop/model_providers/compatible_api.py` — `OllamaProvider`, which uses
  Ollama's **native** `POST /api/chat` endpoint (not the OpenAI-compatible shim) so
  that `prompt_eval_count` and `eval_count` are available.
- `src/verifyloop/config.py` — YAML plus environment overrides, with API keys
  resolved from an environment-variable *name* and never serialized.
- `src/verifyloop/evaluation/evaluator.py` — records provider/model/config in a
  reproducibility manifest before any result is produced.

No benchmark task, strategy definition, scoring rule, or success criterion was
changed. The only new experiment-level choice is the patch format used by the local
pilot config (see §5).

## 2. Configuration

Provider: `ollama`
Base URL: `http://localhost:11434`
Model: `llama3.2:3b` (Q4_K_M, 2.0 GB on disk)
Authentication: none (local Ollama)

Two equivalent ways to select it:

### Environment variables

```powershell
$env:MODEL_PROVIDER="ollama"
$env:MODEL_NAME="llama3.2:3b"
$env:MODEL_BASE_URL="http://localhost:11434"
$env:REQUEST_TIMEOUT_SECONDS="120"
```

### Committed local config

`config/local_ollama.yaml` pins the same values plus small pilot budgets:

- `max_attempts: 2`, `max_model_calls: 6`, `max_wall_clock_seconds: 600`
- `test_timeout_seconds: 60`
- `patch_format: edit_json` (see §5)
- `trials: 1`, all three strategies

The repository-wide default (`config/default.yaml`) still uses the deterministic
`mock` provider so the project remains runnable offline.

## 3. Connection diagnostics

New CLI command:

```powershell
verifyloop provider-check --config config/local_ollama.yaml
# or: python -m verifyloop provider-check --config config/local_ollama.yaml
```

It checks, in order: API reachable → model installed → real generation → response
parsed into non-empty text. Actual output on this machine:

```
provider: ollama
model: llama3.2:3b
base_url: http://localhost:11434

[OK] api_reachable: ollama reachable at http://localhost:11434
[OK] model_installed: llama3.2:3b is installed (3 model(s) available)
[OK] generation: completed in 11.75s (38 prompt + 2 completion tokens)
[OK] response_parseable: 'Ready'

result: PASS
```

Exit codes: `0` pass, `1` check failed, `2` provider configuration error.

Failure paths were exercised without changing the system:

- **Missing model** (`MODEL_NAME=does-not-exist:1b`): fails at `model_installed`,
  lists the installed models, and suggests `ollama pull` without downloading anything.
- **Unreachable server** (`MODEL_BASE_URL=http://localhost:11435`): fails at
  `api_reachable` and suggests `ollama serve`.
- **Memory exhaustion**: the adapter now preserves the server's error body. The
  diagnostic recognizes `unable to allocate`, `CPU_REPACK`, and
  `failed to load model` and explains that the model did not fit in RAM.
- **Timeout**: mapped to `ProviderTimeout` and a hint to raise
  `REQUEST_TIMEOUT_SECONDS`.

The same logic is used by `scripts/probe_provider.py`, so the script and CLI cannot
drift apart.

## 4. Pilot: one small deterministic task

Task: `boundary_paginate_001` (single file, `paging.py`, 15 lines; visible tests are
in the repo, hidden evaluation tests are never shown to the model).

Commands:

```powershell
# Diff-format probe
verifyloop run --config config/local_ollama.yaml `
  --task-ids boundary_paginate_001 --strategies oneshot --trials 1 --max-attempts 1

# Edit-JSON probe
verifyloop run --config config/local_ollama.yaml `
  --task-ids boundary_paginate_001 --strategies oneshot --trials 1 `
  --max-attempts 1 --patch-format edit_json

# Evidence-guided repair probe
verifyloop run --config config/local_ollama.yaml `
  --task-ids boundary_paginate_001 --strategies evidence_guided --trials 1 `
  --max-attempts 2 --patch-format edit_json
```

Actual results:

| Run | Strategy | Format | Attempts | Outcome | Model calls | Tokens (prompt+completion) | Generation (s) | Wall (s) |
|---|---|---|---|---:|---|---:|---:|---:|
| `run-20261020-002400-1ec8b0` | oneshot | diff | 1 | `patch_rejected` | 1 | 556 + 159 | 55.58 | 62.44 |
| `run-20261020-002558-5f8637` | oneshot | edit_json | 1 | `failed_tests` | 1 | 528 + 61 | 15.70 | 34.74 |
| `run-20261020-002658-e39d91` | evidence_guided | edit_json | 2 | `patch_rejected` | 2 | 979 + 94 | 35.22 | 54.28 |
| `run-20261020-014716-223203` | oneshot | diff | 1 | `patch_rejected` | 1 | 556 + 159 | 55.52 | 62.60 |
| `run-20261020-015055-431a09` | oneshot | edit_json (config default) | 1 | `failed_tests` | 1 | 528 + 61 | 14.58 | 27.48 |

The last row is the documented one-line pilot command run **without** a
`--patch-format` override; the run manifest records `patch_format: edit_json`,
`provider: ollama`, and `model: llama3.2:3b`.

### What was verified mechanically

- **Response parsing**: diff text was parsed and rejected with a precise reason;
  edit_json was parsed into an edit list.
- **Validation before application**: path/scope/size checks ran before any write.
- **Application**: the edit_json patch applied to a temporary Git-backed workspace.
- **Tests**: the visible suite ran; the independent hidden-evaluation copy ran in a
  separate workspace the model never saw.
- **Failure recording**: every attempt stores category, rejection reason, token
  usage, generation time, and the exact model text (bounded by
  `max_output_chars`).
- **Model errors**: exercised by the integration suite with a simulated provider
  timeout (`tests/integration/test_controller.py`); the attempt records
  `model_error` and the run ends as an infrastructure error when no budget remains.

### What the model actually did

Diff mode produced a structurally malformed patch (captured verbatim):

```
--- a/paging.py
+++ b/paging.py
@@ -1,7 +1,7 @@
 def paginate(items, page, per_page):
-    """Return one page of ``items``.
+    """Return one page of ``items``.
     """Return one page of ``items``.
     """
     ...
```

The parser rejected it with:

```
paging.py: hunk @@ -1,7 +1,7 @@ declares 7 old lines but contains 11
```

Edit-JSON mode produced a syntactically valid but logically wrong edit:

```json
{"edits": [{"file": "paging.py",
  "search": "end = start + per_page - 1",
  "replace": "end = min(start + per_page - 1, len(items) - 1)"}]}
```

Visible tests then reported `[0, 1] == [0, 1, 2]` (two failures, two passes), which
is the correct diagnosis: the edit did not remove the off-by-one.

On the evidence-guided retry, the model produced:

```json
{"edits": [{"file": "paging.py", "search": "2", "replace": "2, "}]}
```

which was rejected with `search text not found in paging.py` (the search string was
ambiguous/absent; VerifyLoop does not guess at near matches).

## 5. Patch-format finding

At this model size, unified diffs were unreliable: **0/2 diff attempts parsed**,
while **1/1 edit_json attempt parsed and applied**. This is a formatting effect, not
a reasoning effect. `config/local_ollama.yaml` therefore defaults to `edit_json` for
local 3B pilots, and the choice is recorded in every run manifest. The global
default remains `diff`; no scoring or success criterion changed.

This is a single-task observation and is not a general claim about diff vs JSON.

## 6. Resource observations

- Machine: 16 GB RAM, 8 cores, AMD Radeon 610M integrated graphics, no CUDA.
- Free RAM during the pilot: roughly 2.0–2.9 GB. Ollama loaded the 3B model
  successfully; an earlier 8B attempt failed to allocate a ~3.1 GB `CPU_REPACK`
  buffer and is not used here.
- First generation after model load: ~12 s for 2 output tokens (load dominates).
- Real patch generations: ~12–23 s for 33–159 output tokens; two-attempt runs took
  under a minute of generation.
- Runs are sequential by default; no parallelism was enabled.
- Process/temp-directory isolation is scope and resource control, not a security
  sandbox.

## 7. Mock provider and regression status

- `verifyloop smoke-test`: **3/3 scenarios pass** (one-shot success, wrong-then-right
  evidence repair, exhausted failures).
- Unit tests: **115 passed** in 14.23 s.
- Full suite (unit, security, benchmark, integration): **164 passed** in 246.67 s.
- No changes were made to WSL, Docker, n8n, credentials, or unrelated files.

## 8. Limitations and next step

Limitations: one synthetic task, one trial, one model, no GPU, and no statistical
power. No claim is made that evidence-guided repair helps; the pilot shows only that
the full loop runs on a real local model and records failures faithfully.

Recommended next step: run all three strategies on 3–5 small tasks with
`edit_json`, 2–3 attempts, and one trial per (task, strategy), then report paired
counts with the existing McNemar/Wilson tooling. Keep `mock` runs labelled
separately. Do not compare against the 8B model until enough RAM is available to
load it reliably.
