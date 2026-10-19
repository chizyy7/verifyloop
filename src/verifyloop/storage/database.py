"""SQLite persistence for runs and task results.

Schema is intentionally flat and inspectable: one ``runs`` row per experiment and one
``task_results`` row per (task, strategy, trial). The full result document is stored
as JSON alongside the indexed columns used for querying, so the database never becomes
the only copy of the evidence.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from verifyloop.models import TaskResult

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    experiment_name TEXT NOT NULL,
    benchmark_version TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    strategies TEXT NOT NULL,
    trials INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    config_json TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS task_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL,
    strategy TEXT NOT NULL,
    trial INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    verified_success INTEGER NOT NULL,
    attempt_count INTEGER NOT NULL,
    model_calls INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    wall_clock_seconds REAL NOT NULL,
    regression_detected INTEGER NOT NULL,
    budget_exhausted INTEGER NOT NULL,
    failure_category TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE (run_id, task_id, strategy, trial)
);

CREATE INDEX IF NOT EXISTS idx_results_run ON task_results(run_id);
CREATE INDEX IF NOT EXISTS idx_results_task ON task_results(task_id);
CREATE INDEX IF NOT EXISTS idx_results_strategy ON task_results(strategy);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class RunRecord:
    run_id: str
    experiment_name: str
    benchmark_version: str
    provider: str
    model: str
    strategies: list[str]
    trials: int
    created_at: str
    status: str
    config: dict[str, Any]
    manifest: dict[str, Any]
    finished_at: Optional[str] = None
    notes: str = ""


class ExperimentStore:
    """Thin, explicit wrapper over SQLite. No ORM, no hidden magic."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    # -- runs --------------------------------------------------------------

    def create_run(self, record: RunRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (run_id, experiment_name, benchmark_version, provider,
                                  model, strategies, trials, created_at, finished_at,
                                  status, config_json, manifest_json, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.experiment_name,
                    record.benchmark_version,
                    record.provider,
                    record.model,
                    json.dumps(record.strategies),
                    record.trials,
                    record.created_at,
                    record.finished_at,
                    record.status,
                    json.dumps(record.config, sort_keys=True),
                    json.dumps(record.manifest, sort_keys=True),
                    record.notes,
                ),
            )

    def update_run_status(
        self, run_id: str, status: str, *, finished: bool = False
    ) -> None:
        with self._connect() as connection:
            if finished:
                connection.execute(
                    "UPDATE runs SET status = ?, finished_at = ? WHERE run_id = ?",
                    (status, utc_now(), run_id),
                )
            else:
                connection.execute(
                    "UPDATE runs SET status = ? WHERE run_id = ?", (status, run_id)
                )

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return _run_row_to_dict(row) if row else None

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_run_row_to_dict(row) for row in rows]

    # -- results -----------------------------------------------------------

    def save_result(self, result: TaskResult) -> None:
        payload = result.to_dict(include_output=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO task_results
                    (run_id, task_id, strategy, trial, outcome, verified_success,
                     attempt_count, model_calls, total_tokens, wall_clock_seconds,
                     regression_detected, budget_exhausted, failure_category,
                     created_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.run_id,
                    result.task_id,
                    result.strategy,
                    result.trial,
                    result.outcome.value,
                    int(result.outcome.is_success),
                    len(result.attempts),
                    result.model_calls,
                    result.total_tokens,
                    result.wall_clock_seconds,
                    int(result.regression_detected),
                    int(result.budget_exhausted),
                    result.failure_category.value,
                    utc_now(),
                    json.dumps(payload, sort_keys=True),
                ),
            )

    def load_results(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM task_results WHERE run_id = ? "
                "ORDER BY task_id, strategy, trial",
                (run_id,),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def result_count(self, run_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM task_results WHERE run_id = ?", (run_id,)
            ).fetchone()
        return int(row["n"]) if row else 0

    def all_results(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM task_results ORDER BY id"
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def stats(self) -> dict[str, int]:
        with self._connect() as connection:
            runs = connection.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
            results = connection.execute(
                "SELECT COUNT(*) AS n FROM task_results"
            ).fetchone()["n"]
        return {"runs": int(runs), "results": int(results)}


def _run_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["strategies"] = json.loads(data["strategies"])
    data["config"] = json.loads(data.pop("config_json"))
    data["manifest"] = json.loads(data.pop("manifest_json"))
    return data
