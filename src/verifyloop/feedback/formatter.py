"""Render failure evidence and repair prompts as plain text for the model.

Prompt text is deliberately terse and format-strict. Small models fail more often on
output *shape* than on reasoning; the prompts therefore show the exact required
envelope and forbid prose outside it.
"""

from __future__ import annotations

from typing import Sequence

from verifyloop.feedback.analyzer import FailureEvidence

SYSTEM_PROMPT = """You are a senior Python engineer fixing a bug in a small repository.

Rules:
- Make the smallest change that fixes the described defect.
- Do not refactor unrelated code, rename public functions, or reformat files.
- Do not modify or delete tests, conftest.py, or any file outside the source files.
- Output ONLY the patch in the requested format. No explanations, no markdown prose.
"""

DIFF_INSTRUCTIONS = """Output format: a unified diff.
- Begin with `--- a/<path>` and `+++ b/<path>` for each changed file.
- Use `@@ -old_start,old_count +new_start,new_count @@` hunk headers.
- Include 3 lines of unchanged context around each change.
- Every context line starts with a single space, removed lines with `-`, added lines with `+`.
- Line numbers must be consistent with the file content shown to you.
"""

EDIT_JSON_INSTRUCTIONS = """Output format: a single JSON object, nothing else.
{
  "edits": [
    {"file": "<path>", "search": "<exact existing text>", "replace": "<new text>"}
  ]
}
- `search` must match the file exactly, including indentation, and must occur once.
- Keep each edit minimal.
"""


def format_repository_context(files: dict[str, str], *, max_chars: int = 12_000) -> str:
    """Render source files for the prompt, truncating deterministically."""
    chunks: list[str] = []
    used = 0
    for path in sorted(files):
        content = files[path]
        block = f"### File: {path}\n```python\n{content.rstrip()}\n```\n"
        if used + len(block) > max_chars:
            remaining = max_chars - used
            if remaining < 400:
                chunks.append(f"### File: {path}\n[omitted: context budget exhausted]\n")
                break
            block = block[:remaining] + "\n...[truncated]\n```\n"
        chunks.append(block)
        used += len(block)
    return "\n".join(chunks)


def format_initial_prompt(
    task_description: str,
    expected_behavior: str,
    repository_context: str,
    patch_format: str,
) -> str:
    instructions = DIFF_INSTRUCTIONS if patch_format == "diff" else EDIT_JSON_INSTRUCTIONS
    return f"""## Bug report

{task_description.strip()}

## Required behaviour

{expected_behavior.strip()}

## Repository

{repository_context.strip()}

## Output

{instructions.strip()}
"""


def format_evidence_report(evidence: FailureEvidence) -> str:
    """Structured feedback block for the evidence-guided strategy."""
    lines: list[str] = []
    lines.append(f"## Attempt {evidence.attempt} failed")
    lines.append("")
    lines.append(
        f"Tests executed: {evidence.total} "
        f"(passed {evidence.passed}, failed {evidence.failed}, "
        f"errors {evidence.errors}, skipped {evidence.skipped})"
    )

    if evidence.timed_out:
        lines.append("")
        lines.append("The test process exceeded its time limit and was terminated.")
    if evidence.no_tests_collected:
        lines.append("")
        lines.append(
            "No tests were collected. This usually means an import error or a syntax "
            "error in the code you changed."
        )
    if evidence.infrastructure_error:
        lines.append("")
        lines.append(f"Harness reported an infrastructure problem: {evidence.infrastructure_message}")

    if evidence.failing_tests:
        lines.append("")
        lines.append("### Failing tests")
        for entry in evidence.failing_tests:
            lines.append(f"- {entry['test']} [{entry['status']}]")
            if entry.get("message"):
                lines.append(f"  message: {entry['message']}")
            excerpt = entry.get("traceback_excerpt", "")
            if excerpt:
                for excerpt_line in excerpt.splitlines():
                    lines.append(f"  | {excerpt_line}")

    if evidence.regression_tests:
        lines.append("")
        lines.append("### Regressions")
        lines.append(
            "These tests passed before your change and now fail: "
            + ", ".join(evidence.regression_tests)
        )

    if evidence.changed_files:
        lines.append("")
        lines.append("### Files changed by your previous patch")
        for path in evidence.changed_files:
            lines.append(f"- {path}")

    lines.append("")
    lines.append("### Remaining budget")
    lines.append(f"- Repair attempts remaining: {evidence.attempts_remaining}")
    lines.append(f"- Wall-clock seconds remaining: {int(evidence.seconds_remaining)}")

    lines.append("")
    lines.append(
        "Diagnose the root cause of the failure above, then produce a corrected patch "
        "that changes as little as possible."
    )
    return "\n".join(lines)


def format_concise_report(evidence: FailureEvidence, status_listing: str) -> str:
    """Minimal feedback used by the feedback-detail ablation control."""
    lines = [
        f"## Attempt {evidence.attempt} failed",
        "",
        f"{evidence.failed + evidence.errors} test(s) failed.",
        "",
        status_listing or "(no per-test detail available)",
        "",
        "Produce a corrected patch.",
    ]
    return "\n".join(lines)


def format_blind_retry_prompt(attempt: int, patch_format: str) -> str:
    """Feedback-free retry prompt for the blind-retry baseline."""
    instructions = DIFF_INSTRUCTIONS if patch_format == "diff" else EDIT_JSON_INSTRUCTIONS
    return f"""Your previous patch was applied but did not pass the project's tests.

Attempt number: {attempt}.

Try again. Produce a different patch that you believe is correct.
Do not repeat the exact patch you already submitted.

{instructions.strip()}
"""


def format_patch_rejection(
    attempt: int,
    reason: str,
    patch_format: str,
) -> str:
    """Feedback for a patch that never reached the test suite.

    This is deliberately classified separately from a test failure: the model must
    fix the patch *format or scope*, not the program logic.
    """
    instructions = DIFF_INSTRUCTIONS if patch_format == "diff" else EDIT_JSON_INSTRUCTIONS
    return f"""## Attempt {attempt}: patch rejected before execution

Reason: {reason}

This is a patch-format or scope problem, not a test failure. Correct the patch so it
applies to the repository, then resubmit.

{instructions.strip()}
"""


def format_repair_prompt(feedback_block: str, patch_format: str) -> str:
    instructions = DIFF_INSTRUCTIONS if patch_format == "diff" else EDIT_JSON_INSTRUCTIONS
    return f"""{feedback_block.strip()}

## Output

{instructions.strip()}
"""


def estimate_prompt_tokens(text: str) -> int:
    """Rough character-based estimate used only when a provider reports no usage."""
    return max(1, len(text) // 4)
