"""Validation of parsed patches against repository and policy constraints.

This module is a policy gate, not a sandbox. It rejects obviously unsafe or
out-of-scope patches before they reach a working tree. Combined with the
protected-asset snapshot check after application, it covers the realistic failure
modes of a small model: wrong paths, absolute paths, traversal, oversized diffs,
and attempts to rewrite tests.
"""

from __future__ import annotations

import fnmatch
import posixpath
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence

from verifyloop.models import FailureCategory, ValidationResult
from verifyloop.patching.parser import ParsedDiff, iter_patch_targets

#: Paths that are never acceptable patch targets, regardless of configuration.
ALWAYS_PROTECTED: tuple[str, ...] = (
    ".git/**",
    "**/.git/**",
    "conftest.py",
    "**/conftest.py",
    "manifest.json",
    "**/manifest.json",
    "task.json",
    "**/task.json",
    "eval_tests/**",
    "**/eval_tests/**",
    "reference/**",
    "**/reference/**",
    "tests/**",
    "**/tests/**",
    "test_*.py",
    "**/test_*.py",
    "*_test.py",
    "**/*_test.py",
    "*.pem",
    "*.key",
    ".env",
    "**/.env",
)

#: Directories a patch may never create or write into.
FORBIDDEN_DIR_NAMES = frozenset({".git", "__pycache__", ".pytest_cache", ".mypy_cache"})

MAX_FILES_PER_PATCH = 8


def normalize_repo_path(raw: str) -> str:
    """Normalize a patch path and raise ``ValueError`` if it escapes the repo."""
    if not raw or not raw.strip():
        raise ValueError("empty path")
    candidate = raw.strip().replace("\\", "/")
    if "\x00" in candidate:
        raise ValueError("path contains a NUL byte")

    # Windows drive letters and UNC paths.
    if len(candidate) >= 2 and candidate[1] == ":":
        raise ValueError(f"absolute path not allowed: {raw!r}")
    if candidate.startswith("//") or candidate.startswith("\\\\"):
        raise ValueError(f"UNC path not allowed: {raw!r}")

    if candidate.startswith("/"):
        raise ValueError(f"absolute path not allowed: {raw!r}")

    for prefix in ("a/", "b/"):
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix) :]
            break

    # Collapse then verify containment.
    normalized = posixpath.normpath(candidate)
    if normalized in {"", "."}:
        raise ValueError(f"path does not name a file: {raw!r}")
    if normalized.startswith("../") or normalized == "..":
        raise ValueError(f"path traversal not allowed: {raw!r}")
    if normalized.startswith("/"):
        raise ValueError(f"absolute path not allowed: {raw!r}")

    pure = PurePosixPath(normalized)
    if any(part in FORBIDDEN_DIR_NAMES for part in pure.parts):
        raise ValueError(f"path targets a forbidden directory: {raw!r}")
    if any(part == ".." for part in pure.parts):
        raise ValueError(f"path traversal not allowed: {raw!r}")
    return normalized


def matches_any(path: str, patterns: Sequence[str]) -> bool:
    """Glob match supporting ``**`` semantics used by the protected-path lists."""
    normalized = path.replace("\\", "/").lstrip("./")
    for pattern in patterns:
        if fnmatch.fnmatch(normalized, pattern):
            return True
        # ``**/x`` should also match a top-level ``x``.
        if pattern.startswith("**/") and fnmatch.fnmatch(normalized, pattern[3:]):
            return True
        # A bare directory pattern protects everything beneath it.
        if pattern.endswith("/**") and normalized.startswith(pattern[:-3] + "/"):
            return True
    return False


def validate_patch(
    parsed: Any,
    repo_root: Path,
    *,
    protected_patterns: Iterable[str] = (),
    max_patch_bytes: int = 24_000,
    raw_size_bytes: int = 0,
) -> ValidationResult:
    """Validate a parsed patch against path, size, and protection policy.

    Never raises for a bad *patch*; returns ``ValidationResult(ok=False, ...)`` so the
    controller can convert it into feedback. Raises only for programming errors.
    """
    patterns = list(ALWAYS_PROTECTED) + list(protected_patterns)

    if raw_size_bytes and raw_size_bytes > max_patch_bytes:
        return ValidationResult(
            ok=False,
            reason=f"patch is {raw_size_bytes} bytes, limit is {max_patch_bytes}",
            category=FailureCategory.PATCH_FORMAT,
        )

    try:
        targets = list(dict.fromkeys(iter_patch_targets(parsed)))
    except ValueError as exc:
        return ValidationResult(
            ok=False, reason=str(exc), category=FailureCategory.PATCH_PATH
        )

    if not targets:
        return ValidationResult(
            ok=False, reason="patch does not modify any file",
            category=FailureCategory.PATCH_FORMAT,
        )
    if len(targets) > MAX_FILES_PER_PATCH:
        return ValidationResult(
            ok=False,
            reason=f"patch touches {len(targets)} files, limit is {MAX_FILES_PER_PATCH}",
            category=FailureCategory.PATCH_FORMAT,
        )

    normalized: list[str] = []
    for target in targets:
        try:
            clean = normalize_repo_path(target)
        except ValueError as exc:
            return ValidationResult(
                ok=False, reason=str(exc), category=FailureCategory.PATCH_PATH
            )
        if matches_any(clean, patterns):
            return ValidationResult(
                ok=False,
                reason=f"patch targets a protected path: {clean}",
                category=FailureCategory.PATCH_PATH,
            )
        absolute = (repo_root / clean).resolve()
        try:
            absolute.relative_to(repo_root.resolve())
        except ValueError:
            return ValidationResult(
                ok=False,
                reason=f"path escapes the repository: {clean}",
                category=FailureCategory.PATCH_PATH,
            )
        if absolute.exists() and absolute.is_dir():
            return ValidationResult(
                ok=False,
                reason=f"path is a directory: {clean}",
                category=FailureCategory.PATCH_PATH,
            )
        normalized.append(clean)

    if isinstance(parsed, ParsedDiff):
        for file_patch in parsed.files:
            if file_patch.is_delete:
                return ValidationResult(
                    ok=False,
                    reason=f"file deletion is not permitted: {file_patch.path}",
                    category=FailureCategory.PATCH_PATH,
                )
            if file_patch.is_new:
                # New files are allowed only in ordinary source locations.
                if not file_patch.path.endswith(".py"):
                    return ValidationResult(
                        ok=False,
                        reason=f"only .py files may be added: {file_patch.path}",
                        category=FailureCategory.PATCH_PATH,
                    )

    return ValidationResult(ok=True, changed_files=sorted(set(normalized)))
