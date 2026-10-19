"""Isolated working copies for task execution.

Each task attempt runs in a temporary directory outside the project tree (OneDrive
sync interferes with rapid file churn). A local Git repository is created so the
workspace can be reset to a known-good state between attempts with
``git reset --hard`` + ``git clean -fd``.

This is *not* a security sandbox. See ``docs/threat_model.md``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from verifyloop.benchmark.manifest import diff_snapshots, snapshot_tree

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "VerifyLoop",
    "GIT_AUTHOR_EMAIL": "verifyloop@localhost",
    "GIT_COMMITTER_NAME": "VerifyLoop",
    "GIT_COMMITTER_EMAIL": "verifyloop@localhost",
    "GIT_TERMINAL_PROMPT": "0",
}


class WorkspaceError(RuntimeError):
    """Raised when a workspace cannot be created or restored."""


@dataclass
class Workspace:
    """A disposable copy of a task repository with a clean baseline commit."""

    root: Path
    baseline_snapshot: dict[str, str] = field(default_factory=dict)
    _git_available: bool = True

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env={**os.environ, **_GIT_ENV},
        )

    def initialize(self) -> None:
        self.baseline_snapshot = snapshot_tree(self.root)
        result = self._git("init", "--quiet")
        if result.returncode != 0:
            self._git_available = False
            return
        self._git("add", "-A")
        commit = self._git("commit", "--quiet", "-m", "verifyloop baseline")
        if commit.returncode != 0:
            self._git_available = False

    def reset(self) -> None:
        """Restore the workspace to its baseline state."""
        if self._git_available:
            reset = self._git("reset", "--hard", "--quiet", "HEAD")
            clean = self._git("clean", "-fdq")
            if reset.returncode == 0 and clean.returncode == 0:
                return
        # Fallback: rewrite files from the in-memory snapshot.
        self._restore_from_snapshot()

    def _restore_from_snapshot(self) -> None:
        current = snapshot_tree(self.root)
        changes = diff_snapshots(self.baseline_snapshot, current)
        for relative in changes["added"]:
            try:
                (self.root / relative).unlink()
            except OSError:
                pass
        for relative, digest in self.baseline_snapshot.items():
            target = self.root / relative
            if not target.is_file():
                raise WorkspaceError(
                    f"cannot restore {relative}: baseline content is not cached"
                )
        # Content restoration requires the original bytes; keep a pristine mirror.
        mirror = self.root.parent / f"{self.root.name}.baseline"
        if mirror.is_dir():
            for relative in changes["removed"] + changes["modified"]:
                source = mirror / relative
                destination = self.root / relative
                if source.is_file():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)

    def snapshot(self) -> dict[str, str]:
        return snapshot_tree(self.root)

    def capture_contents(self) -> dict[str, str]:
        """Return ``relative_path -> text content`` for every snapshot-tracked file."""
        contents: dict[str, str] = {}
        for relative in snapshot_tree(self.root):
            try:
                contents[relative] = (self.root / relative).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
        return contents

    def changed_since_baseline(self) -> dict[str, list[str]]:
        return diff_snapshots(self.baseline_snapshot, self.snapshot())

    def read_file(self, relative_path: str) -> str:
        return (self.root / relative_path).read_text(encoding="utf-8")

    def write_file(self, relative_path: str, content: str) -> None:
        target = self.root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")

    def list_source_files(self, suffixes: tuple[str, ...] = (".py",)) -> list[str]:
        """Repository-relative source files, excluding tests and caches."""
        files: list[str] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            relative = path.relative_to(self.root)
            parts = set(relative.parts)
            if parts & {"__pycache__", ".git", ".pytest_cache", ".verifyloop"}:
                continue
            if any(part.startswith("test_") for part in relative.parts):
                continue
            files.append(relative.as_posix())
        return files


@contextmanager
def create_workspace(
    source_repo: Path,
    *,
    workspace_root: Path | None = None,
    keep: bool = False,
    prefix: str = "verifyloop-",
) -> Iterator[Workspace]:
    """Copy ``source_repo`` into a fresh temporary workspace."""
    if not source_repo.is_dir():
        raise WorkspaceError(f"source repository not found: {source_repo}")

    base = workspace_root or Path(tempfile.gettempdir())
    base.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=prefix, dir=str(base)))
    root = temp_dir / "repo"

    try:
        shutil.copytree(
            source_repo,
            root,
            ignore=shutil.ignore_patterns(
                "__pycache__", ".git", ".pytest_cache", "*.pyc", ".verifyloop"
            ),
        )
        # Pristine mirror used by the snapshot-based reset fallback.
        mirror = temp_dir / "repo.baseline"
        shutil.copytree(root, mirror)

        workspace = Workspace(root=root)
        workspace.initialize()
        yield workspace
    finally:
        if not keep:
            shutil.rmtree(temp_dir, ignore_errors=True)
