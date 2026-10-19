"""Benchmark manifest and loader tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from verifyloop.benchmark.manifest import (
    BenchmarkError,
    BenchmarkManifest,
    TaskEntry,
    diff_snapshots,
    load_benchmark,
    load_manifest,
    resolve_benchmark_root,
    snapshot_tree,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_ROOT = REPO_ROOT / "benchmarks" / "synthetic"


def test_loads_real_benchmark() -> None:
    manifest, tasks = load_benchmark(BENCHMARK_ROOT, version="v1")
    assert manifest.version == "v1"
    assert len(tasks) == manifest.task_count
    assert len(tasks) >= 10


def test_every_task_has_required_artifacts() -> None:
    _, tasks = load_benchmark(BENCHMARK_ROOT, version="v1")
    for task in tasks:
        assert task.repo_dir.is_dir()
        assert task.eval_tests_dir.is_dir()
        assert task.reference_patch_path.is_file()
        assert task.definition.feedback_command
        assert task.definition.eval_command
        assert task.read_eval_tests()


def test_version_mismatch_rejected() -> None:
    with pytest.raises(BenchmarkError, match="version mismatch"):
        load_benchmark(BENCHMARK_ROOT, version="v999")


def test_unknown_task_id_rejected() -> None:
    with pytest.raises(BenchmarkError, match="unknown task"):
        load_benchmark(BENCHMARK_ROOT, version="v1", task_ids=["nope"])


def test_task_filtering() -> None:
    _, tasks = load_benchmark(
        BENCHMARK_ROOT, version="v1", task_ids=["boundary_paginate_001"]
    )
    assert [task.id for task in tasks] == ["boundary_paginate_001"]


def test_manifest_rejects_duplicate_ids() -> None:
    entry = TaskEntry(
        id="a", title="t", category="c", difficulty="easy", path="p", task_sha256="a" * 64
    )
    with pytest.raises(ValueError):
        BenchmarkManifest(
            name="x", version="v1", task_count=2, tasks=[entry, entry]
        )


def test_manifest_rejects_count_mismatch() -> None:
    with pytest.raises(ValueError, match="task_count"):
        BenchmarkManifest(name="x", version="v1", task_count=5, tasks=[])


def test_tampered_task_json_detected(tmp_path: Path) -> None:
    source = BENCHMARK_ROOT / "v1"
    target = tmp_path / "bench"
    import shutil

    shutil.copytree(source, target)
    task_json = target / "tasks" / "boundary_paginate_001" / "task.json"
    payload = json.loads(task_json.read_text(encoding="utf-8"))
    payload["title"] = "tampered"
    task_json.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BenchmarkError, match="hash mismatch"):
        load_benchmark(target, version="v1")


def test_snapshot_and_diff(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    before = snapshot_tree(tmp_path)
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 1\n", encoding="utf-8")
    after = snapshot_tree(tmp_path)
    changes = diff_snapshots(before, after)
    assert changes["added"] == ["b.py"]
    assert changes["modified"] == ["a.py"]
    assert changes["removed"] == []


def test_snapshot_ignores_caches(tmp_path: Path) -> None:
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_text("junk", encoding="utf-8")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert list(snapshot_tree(tmp_path)) == ["a.py"]


def test_resolve_benchmark_root_accepts_version_dir() -> None:
    assert resolve_benchmark_root(BENCHMARK_ROOT).is_dir()


def test_eval_tests_not_in_repo() -> None:
    _, tasks = load_benchmark(BENCHMARK_ROOT, version="v1")
    for task in tasks:
        assert not list(task.repo_dir.rglob("test_eval_*.py")), task.id


def test_reference_patch_hash_matches() -> None:
    _, tasks = load_benchmark(BENCHMARK_ROOT, version="v1")
    for task in tasks:
        digest = hashlib.sha256(task.reference_patch_path.read_bytes()).hexdigest()
        assert digest == task.definition.reference_fix_sha256, task.id
