"""Read-only audit of benchmark tasks for pilot selection.

Prints, for every task: category, difficulty, source size, visible-test size,
hidden-evaluation size, test names, assertion counts, and whether visible and hidden
test names overlap. It never writes to the benchmark or executes model code.

Usage:
    python scripts/audit_pilot_tasks.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "benchmarks" / "synthetic" / "v1"
TEST_DEF = re.compile(r"^\s*def (test_[A-Za-z0-9_]+)\s*\(", re.MULTILINE)


def test_names(files: list[Path]) -> list[str]:
    names: list[str] = []
    for path in files:
        names.extend(TEST_DEF.findall(path.read_text(encoding="utf-8")))
    return names


def assert_count(files: list[Path]) -> int:
    total = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        total += len(re.findall(r"^\s*assert\s+", text, re.MULTILINE))
    return total


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def main() -> int:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["tasks"]:
        task_dir = ROOT / entry["path"]
        task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        repo = task_dir / task["repo_dir"]
        sources = sorted(
            path
            for path in repo.rglob("*.py")
            if "tests" not in path.relative_to(repo).parts and path.name != "conftest.py"
        )
        visible = sorted((repo / "tests").rglob("*.py")) if (repo / "tests").is_dir() else []
        hidden = sorted((task_dir / "eval_tests").rglob("*.py"))
        visible_names = test_names(visible)
        hidden_names = test_names(hidden)
        overlap = sorted(set(visible_names) & set(hidden_names))
        ref = task_dir / task["reference_fix"]

        print(f"\n=== {task['id']} [{task['category']} / {task['difficulty']}] ===")
        print(f"title: {task['title']}")
        print(
            f"source files: "
            + ", ".join(f"{p.relative_to(repo).as_posix()} ({line_count(p)} lines)" for p in sources)
        )
        print(
            f"visible: {len(visible_names)} tests, {assert_count(visible)} asserts "
            f"| hidden: {len(hidden_names)} tests, {assert_count(hidden)} asserts "
            f"| reference patch: {line_count(ref)} lines"
        )
        print(f"visible tests: {', '.join(visible_names) or '(none)'}")
        print(f"hidden tests:  {', '.join(hidden_names) or '(none)'}")
        if overlap:
            print(f"name overlap:  {', '.join(overlap)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
