"""Allowlisted subprocess execution with hard limits.

Security posture (see ``docs/threat_model.md``): this is a *resource and scope*
control, not a security sandbox. It prevents accidental damage from a confused
model: wrong interpreter, unbounded runtime, runaway output, or a command that was
not approved. It does not contain deliberately malicious code. The benchmark corpus
is locally generated and trusted.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence


class CommandNotAllowed(PermissionError):
    """Raised when a command is outside the allowlist."""


@dataclass
class ExecutionLimits:
    timeout_seconds: float = 120.0
    max_output_bytes: int = 60_000
    max_memory_mb: Optional[int] = None  # reserved; not enforced on Windows


@dataclass
class RawExecution:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    launch_error: str = ""
    truncated: bool = False
    resolved_executable: str = ""
    env_notes: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.timed_out and not self.launch_error and self.exit_code == 0


def resolve_executable(command: str, allowed: Sequence[str]) -> str:
    """Map an allowlisted command name to an absolute executable path."""
    if command not in allowed:
        raise CommandNotAllowed(f"command not in allowlist: {command!r}")

    if command in {"python", "python3"}:
        return sys.executable
    if command == "py":
        found = shutil.which("py")
        if not found:
            raise CommandNotAllowed("'py' launcher is not available on this system")
        return found
    if command == "pytest":
        found = shutil.which("pytest")
        if found:
            return found
        return sys.executable
    raise CommandNotAllowed(f"no resolver for command: {command!r}")


def build_command(argv: Sequence[str], allowed: Sequence[str]) -> list[str]:
    """Turn a declared argv into a concrete executable argument list."""
    if not argv:
        raise ValueError("command must not be empty")
    head = argv[0]
    resolved = resolve_executable(head, allowed)
    rest = list(argv[1:])
    if head in {"python", "python3", "py"} and resolved == sys.executable:
        return [resolved, *rest]
    if head == "pytest" and resolved == sys.executable:
        return [resolved, "-m", "pytest", *rest]
    return [resolved, *rest]


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return text, False
    head = limit // 2
    tail = limit - head
    clipped = (
        encoded[:head].decode("utf-8", errors="replace")
        + "\n... [output truncated by VerifyLoop] ...\n"
        + encoded[-tail:].decode("utf-8", errors="replace")
    )
    return clipped, True


def run_command(
    argv: Sequence[str],
    cwd: Path,
    *,
    allowed_commands: Sequence[str],
    limits: ExecutionLimits | None = None,
    extra_env: Optional[dict[str, str]] = None,
) -> RawExecution:
    """Run one allowlisted command with a timeout and capped output."""
    limits = limits or ExecutionLimits()
    command = build_command(argv, allowed_commands)

    env = os.environ.copy()
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            # Third-party pytest plugins add ~8s per invocation on this machine and
            # make timing measurements non-comparable across environments. The
            # benchmark needs only core pytest; project-local conftest.py files are
            # unaffected by this setting.
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "NO_COLOR": "1",
        }
    )
    if extra_env:
        env.update(extra_env)

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            timeout=limits.timeout_seconds,
            check=False,
        )
        duration = time.monotonic() - started
        stdout = completed.stdout.decode("utf-8", errors="replace")
        stderr = completed.stderr.decode("utf-8", errors="replace")
        stdout, truncated_out = _truncate(stdout, limits.max_output_bytes)
        stderr, truncated_err = _truncate(stderr, limits.max_output_bytes // 2)
        return RawExecution(
            command=command,
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            truncated=truncated_out or truncated_err,
            resolved_executable=command[0],
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        stdout = (exc.stdout or b"").decode("utf-8", errors="replace")
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
        stdout, _ = _truncate(stdout, limits.max_output_bytes)
        stderr, _ = _truncate(stderr, limits.max_output_bytes // 2)
        return RawExecution(
            command=command,
            exit_code=-1,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            timed_out=True,
            resolved_executable=command[0],
        )
    except OSError as exc:
        duration = time.monotonic() - started
        return RawExecution(
            command=command,
            exit_code=-1,
            stdout="",
            stderr="",
            duration_seconds=duration,
            launch_error=str(exc),
            resolved_executable=command[0] if command else "",
        )
