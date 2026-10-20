"""Classify raw pytest output into a structured :class:`TestReport`.

Two independent signals are combined:

1. **JUnit XML** (written via ``--junitxml``) gives reliable per-test statuses.
2. **Console text** provides fallback detail and disambiguates "no tests collected"
   from "collection error" from "all passed".

A report with zero collected tests is never treated as success, regardless of exit
code. pytest exit codes are used as a cross-check, not as the sole source of truth.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from verifyloop.execution.runner import RawExecution
from verifyloop.models import FailureCategory, TestCaseResult, TestReport
from verifyloop.redaction import redact_text

# Documented pytest exit codes.
PYTEST_EXIT_OK = 0
PYTEST_EXIT_TESTS_FAILED = 1
PYTEST_EXIT_INTERRUPTED = 2
PYTEST_EXIT_INTERNAL_ERROR = 3
PYTEST_EXIT_USAGE_ERROR = 4
PYTEST_EXIT_NO_TESTS = 5

_COLLECTED_RE = re.compile(r"collected\s+(\d+)\s+item")
_NO_TESTS_RE = re.compile(r"no tests ran", re.IGNORECASE)
_ERRORS_RE = re.compile(r"^ERROR\s+(.+)$", re.MULTILINE)
_FAILED_RE = re.compile(r"^(FAILED|ERROR)\s+(\S+)(?:\s+-\s+(.*))?$", re.MULTILINE)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_ABS_PY_PATH_RE = re.compile(r'[A-Za-z]:\\[^"\n]*?\\([^"\\/\n]+\.py)')
_COLLECTION_NOISE = (
    "site-packages",
    "<frozen importlib",
    "importlib._bootstrap",
    "\\lib\\importlib",
    "/lib/importlib",
    "_pytest",
    "pluggy",
)

MAX_COLLECTION_EXCERPT_CHARS = 2_400
MAX_COLLECTION_EXCERPT_LINES = 40
MAX_COLLECTION_LINE_CHARS = 400


def _clean_collection_lines(lines: list[str]) -> list[str]:
    """Remove harness/environment frames while keeping the actionable error."""
    cleaned: list[str] = []
    for line in lines:
        lowered = line.lower()
        stripped = line.strip()
        if any(noise in lowered for noise in _COLLECTION_NOISE):
            continue
        if stripped.startswith(
            (
                "mod = import_path(",
                "importlib.import_module(",
                "return _bootstrap",
                "exec(co, module.__dict__)",
            )
        ):
            continue
        if stripped in {"???", "..."}:
            continue
        cleaned.append(_ABS_PY_PATH_RE.sub(r"\1", line))
    return cleaned


def extract_collection_error(stdout: str, stderr: str) -> str:
    """Return a bounded, redacted pytest collection-error excerpt.

    The useful part of a collection failure is the ``ERRORS`` section: it contains
    the import/syntax exception and the source line, unlike the JUnit XML element,
    which usually only says ``collection failure``. We deliberately stop before the
    short test summary and cap both line count and characters so unrelated console
    output is not sent back to the model.
    """
    combined = _ANSI_RE.sub("", f"{stdout}\n{stderr}")
    lines = combined.splitlines()
    if not lines:
        return ""

    starts: list[int] = []
    for index, line in enumerate(lines):
        lowered = line.strip().lower()
        if "error collecting" in lowered or "error during collection" in lowered:
            # Include the ERRORS banner immediately above the collecting line when
            # present, but do not treat every ERRORS section (e.g. teardown errors)
            # as a collection failure.
            start = index
            for lookback in range(index - 1, max(-1, index - 4), -1):
                candidate = lines[lookback].strip()
                if candidate.startswith("====") and "errors" in candidate.lower():
                    start = lookback
                    break
            starts.append(start)
    if not starts:
        return ""

    start = min(starts)
    end = len(lines)
    for index in range(start + 1, len(lines)):
        stripped = lines[index].strip()
        lowered = stripped.lower()
        if stripped.startswith("====") and "short test summary" in lowered:
            end = index
            break
        if stripped.startswith("!!!!") and "interrupted" in lowered:
            end = index + 1
            break
        if index - start >= MAX_COLLECTION_EXCERPT_LINES:
            end = index
            break

    excerpt_lines = [
        line[:MAX_COLLECTION_LINE_CHARS].rstrip()
        for line in lines[start:end]
        if line.strip()
    ]
    excerpt_lines = _clean_collection_lines(excerpt_lines)
    if not excerpt_lines:
        return ""
    excerpt = redact_text("\n".join(excerpt_lines)).strip()
    if len(excerpt) > MAX_COLLECTION_EXCERPT_CHARS:
        excerpt = excerpt[: MAX_COLLECTION_EXCERPT_CHARS - 20].rstrip()
        excerpt += "\n... [excerpt truncated]"
    return excerpt


def _parse_junit(path: Path) -> tuple[list[TestCaseResult], str]:
    """Parse a JUnit XML file. Returns cases and a non-fatal error string."""
    if not path.is_file():
        return [], ""
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        return [], f"junit xml parse error: {exc}"

    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    cases: list[TestCaseResult] = []
    for suite in suites:
        for element in suite.iter("testcase"):
            name = element.get("name", "<unnamed>")
            classname = element.get("classname", "")
            full_name = f"{classname}::{name}" if classname else name
            duration = float(element.get("time", "0") or 0)
            file_name = element.get("file", "")

            failure = element.find("failure")
            error = element.find("error")
            skipped = element.find("skipped")

            if failure is not None:
                cases.append(
                    TestCaseResult(
                        name=full_name,
                        status="failed",
                        duration_seconds=duration,
                        message=_clip((failure.get("message") or failure.text or "").strip()),
                        file=file_name,
                    )
                )
            elif error is not None:
                cases.append(
                    TestCaseResult(
                        name=full_name,
                        status="error",
                        duration_seconds=duration,
                        message=_clip((error.get("message") or error.text or "").strip()),
                        file=file_name,
                    )
                )
            elif skipped is not None:
                cases.append(
                    TestCaseResult(
                        name=full_name,
                        status="skipped",
                        duration_seconds=duration,
                        message=_clip(skipped.get("message", "")),
                        file=file_name,
                    )
                )
            else:
                cases.append(
                    TestCaseResult(
                        name=full_name,
                        status="passed",
                        duration_seconds=duration,
                        file=file_name,
                    )
                )
    return cases, ""


def _clip(text: str, limit: int = 1200) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + " ...[truncated]"


def classify_execution(raw: RawExecution, junit_path: Path | None = None) -> TestReport:
    """Build a :class:`TestReport` from a raw execution."""
    combined = f"{raw.stdout}\n{raw.stderr}"
    collection_excerpt = extract_collection_error(raw.stdout, raw.stderr)

    if raw.timed_out:
        return TestReport(
            command=raw.command,
            exit_code=raw.exit_code,
            duration_seconds=raw.duration_seconds,
            stdout=raw.stdout,
            stderr=raw.stderr,
            collection_error_excerpt=collection_excerpt,
            timed_out=True,
        )

    if raw.launch_error:
        return TestReport(
            command=raw.command,
            exit_code=raw.exit_code,
            duration_seconds=raw.duration_seconds,
            stdout=raw.stdout,
            stderr=raw.stderr,
            collection_error_excerpt=collection_excerpt,
            infrastructure_error=True,
            infrastructure_message=raw.launch_error,
        )

    cases: list[TestCaseResult] = []
    junit_error = ""
    if junit_path is not None:
        cases, junit_error = _parse_junit(junit_path)

    if not cases:
        cases = _parse_console_cases(combined)

    # Missing dependency / import failure at collection time.
    infra_message = ""
    if "ModuleNotFoundError" in combined and raw.exit_code in {
        PYTEST_EXIT_USAGE_ERROR,
        PYTEST_EXIT_INTERNAL_ERROR,
    }:
        infra_message = "test run failed due to a missing module"
    elif "INTERNALERROR" in combined:
        infra_message = "pytest reported an internal error"
    elif junit_error:
        infra_message = junit_error

    if infra_message:
        return TestReport(
            command=raw.command,
            exit_code=raw.exit_code,
            duration_seconds=raw.duration_seconds,
            cases=cases,
            stdout=raw.stdout,
            stderr=raw.stderr,
            collection_error_excerpt=collection_excerpt,
            infrastructure_error=True,
            infrastructure_message=infra_message,
        )

    return TestReport(
        command=raw.command,
        exit_code=raw.exit_code,
        duration_seconds=raw.duration_seconds,
        cases=cases,
        stdout=raw.stdout,
        stderr=raw.stderr,
        collection_error_excerpt=collection_excerpt,
    )


def _parse_console_cases(text: str) -> list[TestCaseResult]:
    """Best-effort per-test extraction from pytest's short summary."""
    cases: dict[str, TestCaseResult] = {}
    for match in _FAILED_RE.finditer(text):
        kind, nodeid, message = match.group(1), match.group(2), match.group(3) or ""
        cases[nodeid] = TestCaseResult(
            name=nodeid,
            status="failed" if kind == "FAILED" else "error",
            message=_clip(message),
        )

    collected_match = _COLLECTED_RE.search(text)
    if not cases and collected_match and "failed" not in text.lower():
        count = int(collected_match.group(1))
        for index in range(count):
            # Console-only pass detection cannot name individual tests reliably.
            cases[f"collected_test_{index + 1}"] = TestCaseResult(
                name=f"collected_test_{index + 1}", status="passed"
            )
    return list(cases.values())


def categorize_failure(report: TestReport) -> FailureCategory:
    """Map a failed report onto a coarse failure category."""
    if report.timed_out:
        return FailureCategory.TIMEOUT
    if report.infrastructure_error:
        return FailureCategory.ENVIRONMENT_ERROR
    if report.collection_failed:
        text = f"{report.stdout}\n{report.stderr}\n{report.collection_error_excerpt}"
        if "SyntaxError" in text:
            return FailureCategory.SYNTAX_ERROR
        if "ModuleNotFoundError" in text or "ImportError" in text:
            return FailureCategory.IMPORT_ERROR
        return FailureCategory.COLLECTION_ERROR
    if report.total == 0:
        text = f"{report.stdout}\n{report.stderr}"
        if "SyntaxError" in text:
            return FailureCategory.SYNTAX_ERROR
        if "error" in text.lower() and "collect" in text.lower():
            return FailureCategory.COLLECTION_ERROR
        return FailureCategory.NO_TESTS_COLLECTED
    if report.all_passed:
        return FailureCategory.NONE

    text = "\n".join(case.message for case in report.failing_cases())
    combined = f"{text}\n{report.stdout}\n{report.stderr}"
    if "SyntaxError" in combined:
        return FailureCategory.SYNTAX_ERROR
    if "ModuleNotFoundError" in combined or "ImportError" in combined:
        return FailureCategory.IMPORT_ERROR
    if "AssertionError" in combined:
        return FailureCategory.ASSERTION
    if report.errors:
        return FailureCategory.EXCEPTION
    return FailureCategory.UNKNOWN


def count_console_collected(text: str) -> int | None:
    """Extract pytest's reported collected count, if present."""
    match = _COLLECTED_RE.search(text)
    return int(match.group(1)) if match else None
