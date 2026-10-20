"""Tests for persistence and exports."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from verifyloop.models import Outcome, TaskResult
from verifyloop.storage.database import ExperimentStore, RunRecord
from verifyloop.storage.exports import export_csv, export_jsonl, export_summary


def make_result(run_id: str = "run-1", task: str = "t1") -> TaskResult:
    return TaskResult(
        run_id=run_id,
        task_id=task,
        strategy="oneshot",
        model="mock-scripted",
        provider="mock",
        benchmark_version="v1",
        trial=0,
        outcome=Outcome.VERIFIED_SUCCESS,
        model_calls=1,
        prompt_tokens=10,
        completion_tokens=5,
        wall_clock_seconds=1.5,
    )


def make_run(run_id: str = "run-1") -> RunRecord:
    return RunRecord(
        run_id=run_id,
        experiment_name="test",
        benchmark_version="v1",
        provider="mock",
        model="mock-scripted",
        strategies=["oneshot"],
        trials=1,
        created_at="2026-01-01T00:00:00+00:00",
        status="running",
        config={"name": "test"},
        manifest={"run_id": run_id},
    )


def test_store_round_trip(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path / "test.db")
    store.create_run(make_run())
    store.save_result(make_result())
    results = store.load_results("run-1")
    assert len(results) == 1
    assert results[0]["task_id"] == "t1"
    assert results[0]["outcome"] == "verified_success"


def test_store_updates_status(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path / "test.db")
    store.create_run(make_run())
    store.update_run_status("run-1", "completed", finished=True)
    run = store.get_run("run-1")
    assert run is not None
    assert run["status"] == "completed"
    assert run["finished_at"] is not None


def test_store_deduplicates_results(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path / "test.db")
    store.create_run(make_run())
    store.save_result(make_result())
    store.save_result(make_result())
    assert store.result_count("run-1") == 1


def test_store_stats(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path / "test.db")
    store.create_run(make_run())
    store.save_result(make_result())
    stats = store.stats()
    assert stats == {"runs": 1, "results": 1}


def test_run_config_is_persisted_as_json(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path / "test.db")
    store.create_run(make_run())
    run = store.get_run("run-1")
    assert run["config"] == {"name": "test"}
    assert run["strategies"] == ["oneshot"]


def test_export_jsonl(tmp_path: Path) -> None:
    results = [make_result().to_dict(include_output=True)]
    path = export_jsonl(results, tmp_path / "out.jsonl")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["task_id"] == "t1"


def test_export_csv(tmp_path: Path) -> None:
    results = [make_result().to_dict(include_output=True)]
    path = export_csv(results, tmp_path / "out.csv")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["verified_success"] == "1"
    assert rows[0]["strategy"] == "oneshot"


def test_export_csv_has_stable_columns(tmp_path: Path) -> None:
    results = [make_result().to_dict()]
    path = export_csv(results, tmp_path / "out.csv")
    header = path.read_text(encoding="utf-8").splitlines()[0]
    assert "wall_clock_seconds" in header
    assert "failure_category" in header
    assert "test_reachability" in header
    assert "attempts_patch_applied" in header
    assert "attempts_with_collection_error" in header


def test_export_summary(tmp_path: Path) -> None:
    path = export_summary({"a": 1}, tmp_path / "summary.json")
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}


def test_export_creates_parent_dirs(tmp_path: Path) -> None:
    path = export_jsonl([], tmp_path / "deep" / "nested" / "out.jsonl")
    assert path.is_file()
