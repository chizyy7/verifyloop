"""Benchmark manifest schema, loading, and integrity validation.

The manifest is the only entry point the rest of the engine uses. Hidden evaluation
tests and reference fixes are deliberately *not* exposed by :class:`TaskDefinition`
in a form the prompt builder can serialize: they live on disk behind accessors that
the controller only calls at evaluation time.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator

TASK_MANIFEST_SCHEMA_VERSION = 1


class TaskEntry(BaseModel):
    """One task as listed in ``manifest.json``."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1)
    category: str = Field(min_length=1)
    difficulty: str = Field(min_length=1)
    path: str = Field(min_length=1)
    task_sha256: str = Field(min_length=64, max_length=64)


class BenchmarkManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    description: str = ""
    task_count: int = Field(ge=0)
    categories: list[str] = Field(default_factory=list)
    tasks: list[TaskEntry] = Field(default_factory=list)

    @field_validator("tasks")
    @classmethod
    def _unique_ids(cls, value: list[TaskEntry]) -> list[TaskEntry]:
        seen: set[str] = set()
        for entry in value:
            if entry.id in seen:
                raise ValueError(f"duplicate task id: {entry.id}")
            seen.add(entry.id)
        return value

    def model_post_init(self, _context: Any) -> None:
        if self.task_count != len(self.tasks):
            raise ValueError(
                f"task_count={self.task_count} does not match {len(self.tasks)} entries"
            )


class TaskDefinition(BaseModel):
    """Validated per-task metadata (``tasks/<id>/task.json``)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str
    category: str
    difficulty: str
    expected_behavior: str
    repo_dir: str = "repo"
    feedback_test_paths: list[str] = Field(default_factory=list)
    feedback_command: list[str] = Field(default_factory=list)
    eval_command: list[str] = Field(default_factory=list)
    reference_fix: str = "reference/fix.patch"
    reference_fix_sha256: str = ""
    synthetic: bool = True
    notes: str = ""

    @field_validator("feedback_command", "eval_command")
    @classmethod
    def _non_empty_command(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("command must not be empty")
        return value


@dataclass
class LoadedTask:
    """A task resolved to absolute paths on disk."""

    definition: TaskDefinition
    task_dir: Path
    repo_dir: Path
    eval_tests_dir: Path
    reference_patch_path: Path
    benchmark_version: str
    entry_sha256: str
    _eval_cache: list[tuple[str, str]] | None = field(default=None, repr=False)

    @property
    def id(self) -> str:
        return self.definition.id

    @property
    def title(self) -> str:
        return self.definition.title

    @property
    def category(self) -> str:
        return self.definition.category

    @property
    def difficulty(self) -> str:
        return self.definition.difficulty

    def read_eval_tests(self) -> list[tuple[str, str]]:
        """Return ``(relative_path, content)`` for hidden evaluation tests.

        Callers must be evaluation code. Nothing in this method is prompt-safe.
        """
        if self._eval_cache is None:
            pairs: list[tuple[str, str]] = []
            for path in sorted(self.eval_tests_dir.rglob("*.py")):
                pairs.append(
                    (path.relative_to(self.eval_tests_dir).as_posix(),
                     path.read_text(encoding="utf-8"))
                )
            self._eval_cache = pairs
        return list(self._eval_cache)

    def read_reference_patch(self) -> str:
        """Return the reference patch text. Evaluation/validation use only."""
        return self.reference_patch_path.read_text(encoding="utf-8")

    def protected_globs(self) -> list[str]:
        """Globs that a model patch may never touch inside this task's repo."""
        return [
            "conftest.py",
            "tests/**",
            "eval_tests/**",
            "reference/**",
            "task.json",
            "manifest.json",
        ]


class BenchmarkError(RuntimeError):
    """Raised when the benchmark corpus is missing or internally inconsistent."""


def resolve_benchmark_root(root: str | Path) -> Path:
    """Resolve a benchmark root relative to CWD, the repo, or the installed package."""
    candidate = Path(root)
    if candidate.is_absolute():
        return candidate
    cwd_candidate = Path.cwd() / candidate
    if cwd_candidate.is_dir():
        return cwd_candidate
    repo_candidate = Path(__file__).resolve().parents[3] / candidate
    if repo_candidate.is_dir():
        return repo_candidate
    return cwd_candidate


def load_manifest(benchmark_root: Path) -> BenchmarkManifest:
    manifest_path = benchmark_root / "manifest.json"
    if not manifest_path.is_file():
        raise BenchmarkError(f"manifest not found: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BenchmarkError(f"manifest is not valid JSON: {exc}") from exc
    return BenchmarkManifest.model_validate(payload)


def load_task(benchmark_root: Path, entry: TaskEntry, version: str) -> LoadedTask:
    task_dir = benchmark_root / entry.path
    if not task_dir.is_dir():
        raise BenchmarkError(f"task directory missing: {task_dir}")
    task_json = task_dir / "task.json"
    if not task_json.is_file():
        raise BenchmarkError(f"task.json missing: {task_json}")

    actual_hash = hashlib.sha256(task_json.read_bytes()).hexdigest()
    if actual_hash != entry.task_sha256:
        raise BenchmarkError(
            f"task {entry.id}: task.json hash mismatch "
            f"(manifest {entry.task_sha256[:12]}..., disk {actual_hash[:12]}...)"
        )

    definition = TaskDefinition.model_validate_json(task_json.read_text(encoding="utf-8"))
    if definition.id != entry.id:
        raise BenchmarkError(
            f"task {entry.id}: task.json declares id {definition.id!r}"
        )

    repo_dir = task_dir / definition.repo_dir
    if not repo_dir.is_dir():
        raise BenchmarkError(f"task {entry.id}: repo directory missing: {repo_dir}")

    eval_tests_dir = task_dir / "eval_tests"
    if not eval_tests_dir.is_dir():
        raise BenchmarkError(f"task {entry.id}: eval_tests directory missing")

    reference_patch_path = task_dir / definition.reference_fix
    if not reference_patch_path.is_file():
        raise BenchmarkError(f"task {entry.id}: reference fix missing")

    patch_bytes = reference_patch_path.read_bytes()
    actual_patch_hash = hashlib.sha256(patch_bytes).hexdigest()
    if (
        definition.reference_fix_sha256
        and actual_patch_hash != definition.reference_fix_sha256
    ):
        raise BenchmarkError(f"task {entry.id}: reference patch hash mismatch")

    return LoadedTask(
        definition=definition,
        task_dir=task_dir,
        repo_dir=repo_dir,
        eval_tests_dir=eval_tests_dir,
        reference_patch_path=reference_patch_path,
        benchmark_version=version,
        entry_sha256=entry.task_sha256,
    )


def load_benchmark(
    root: str | Path,
    *,
    version: str | None = None,
    task_ids: Iterable[str] | None = None,
) -> tuple[BenchmarkManifest, list[LoadedTask]]:
    """Load and validate a benchmark corpus.

    ``version`` is checked against the manifest so an experiment can never silently
    run against a different corpus revision than the one it recorded.
    """
    benchmark_root = resolve_benchmark_root(root)
    # Support both a flat corpus (``root/manifest.json``) and a versioned layout
    # (``root/<version>/manifest.json``).
    candidates = [benchmark_root]
    if version is not None:
        candidates.insert(0, benchmark_root / version)
    if benchmark_root.is_dir():
        candidates.extend(sorted(path for path in benchmark_root.iterdir() if path.is_dir()))
    chosen: Path | None = None
    for candidate in candidates:
        if (candidate / "manifest.json").is_file():
            chosen = candidate
            break
    if chosen is None:
        raise BenchmarkError(
            "manifest not found; looked in: "
            + ", ".join(str(candidate / "manifest.json") for candidate in candidates)
        )
    benchmark_root = chosen
    manifest = load_manifest(benchmark_root)
    if version is not None and manifest.version != version:
        raise BenchmarkError(
            f"benchmark version mismatch: requested {version!r}, "
            f"manifest is {manifest.version!r}"
        )

    requested = list(task_ids or [])
    entries = manifest.tasks
    if requested:
        known = {entry.id for entry in entries}
        unknown = [task_id for task_id in requested if task_id not in known]
        if unknown:
            raise BenchmarkError(f"unknown task ids: {', '.join(sorted(unknown))}")
        by_id = {entry.id: entry for entry in entries}
        entries = [by_id[task_id] for task_id in requested]

    tasks = [load_task(benchmark_root, entry, manifest.version) for entry in entries]
    return manifest, tasks


def snapshot_tree(
    root: Path,
    *,
    ignore: Iterable[str] = (".git", "__pycache__", ".pytest_cache", ".verifyloop"),
) -> dict[str, str]:
    """Return ``relative_path -> sha256`` for every file under ``root``."""
    ignored = set(ignore)
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        parts = set(path.relative_to(root).parts)
        if parts & ignored:
            continue
        result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def diff_snapshots(
    before: dict[str, str], after: dict[str, str]
) -> dict[str, list[str]]:
    """Compare two snapshots, returning added/removed/modified relative paths."""
    before_keys, after_keys = set(before), set(after)
    return {
        "added": sorted(after_keys - before_keys),
        "removed": sorted(before_keys - after_keys),
        "modified": sorted(
            key for key in before_keys & after_keys if before[key] != after[key]
        ),
    }
