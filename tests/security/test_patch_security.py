"""Security-focused tests for patch validation.

These are the tests that protect the evaluation from a model that tries to rewrite
its own tests, escape the repository, or smuggle in oversized changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from verifyloop.patching.parser import parse_unified_diff
from verifyloop.patching.validator import (
    matches_any,
    normalize_repo_path,
    validate_patch,
)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test(): pass\n", encoding="utf-8")
    return tmp_path


def make_diff(path: str, old: str = "x = 1", new: str = "x = 2") -> str:
    return (
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -1,1 +1,1 @@\n"
        f"-{old}\n"
        f"+{new}\n"
    )


@pytest.mark.parametrize(
    "raw",
    [
        "/etc/passwd",
        "../outside.py",
        "../../etc/shadow",
        "C:/Windows/system32/config",
        "C:\\Windows\\win.ini",
        "\\\\server\\share\\file.py",
        "a/../../escape.py",
    ],
)
def test_rejects_unsafe_paths(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_repo_path(raw)


def test_accepts_normal_paths() -> None:
    assert normalize_repo_path("src/app.py") == "src/app.py"
    assert normalize_repo_path("a/src/app.py") == "src/app.py"
    assert normalize_repo_path("b/app.py") == "app.py"


def test_rejects_git_directory() -> None:
    with pytest.raises(ValueError):
        normalize_repo_path(".git/config")


def test_rejects_tests_directory(repo: Path) -> None:
    parsed = parse_unified_diff(make_diff("tests/test_app.py", "def test(): pass", "def test(): assert 1"))
    result = validate_patch(parsed, repo)
    assert not result.ok
    assert result.category.value == "patch_path"
    assert "protected" in result.reason


def test_rejects_conftest(repo: Path) -> None:
    parsed = parse_unified_diff(make_diff("conftest.py", "import os", "import sys"))
    result = validate_patch(parsed, repo)
    assert not result.ok


def test_rejects_task_manifest(repo: Path) -> None:
    parsed = parse_unified_diff(make_diff("task.json", "{}", '{"x": 1}'))
    result = validate_patch(parsed, repo)
    assert not result.ok


def test_rejects_absolute_path_diff(repo: Path) -> None:
    parsed = parse_unified_diff(make_diff("/etc/passwd", "root", "hacked"))
    result = validate_patch(parsed, repo)
    assert not result.ok
    assert result.category.value == "patch_path"


def test_rejects_oversized_patch(repo: Path) -> None:
    parsed = parse_unified_diff(make_diff("app.py"))
    result = validate_patch(parsed, repo, max_patch_bytes=10, raw_size_bytes=5000)
    assert not result.ok
    assert "limit is" in result.reason


def test_accepts_ordinary_source_change(repo: Path) -> None:
    parsed = parse_unified_diff(make_diff("app.py"))
    result = validate_patch(parsed, repo)
    assert result.ok
    assert result.changed_files == ["app.py"]


def test_rejects_too_many_files(repo: Path) -> None:
    for index in range(10):
        (repo / f"m{index}.py").write_text("a = 1\n", encoding="utf-8")
    text = "".join(make_diff(f"m{index}.py") for index in range(10))
    parsed = parse_unified_diff(text)
    result = validate_patch(parsed, repo)
    assert not result.ok
    assert "files" in result.reason


def test_rejects_file_deletion(repo: Path) -> None:
    text = """--- a/app.py
+++ /dev/null
@@ -1,1 +0,0 @@
-x = 1
"""
    parsed = parse_unified_diff(text)
    result = validate_patch(parsed, repo)
    assert not result.ok


def test_rejects_non_python_new_file(repo: Path) -> None:
    text = """--- /dev/null
+++ b/evil.sh
@@ -0,0 +1,1 @@
+rm -rf /
"""
    parsed = parse_unified_diff(text)
    result = validate_patch(parsed, repo)
    assert not result.ok


def test_custom_protected_patterns(repo: Path) -> None:
    (repo / "secret_config.py").write_text("key = 'x'\n", encoding="utf-8")
    parsed = parse_unified_diff(make_diff("secret_config.py", "key = 'x'", "key = 'y'"))
    assert validate_patch(parsed, repo).ok
    result = validate_patch(parsed, repo, protected_patterns=["secret_config.py"])
    assert not result.ok


def test_matches_any_double_star() -> None:
    assert matches_any("tests/test_a.py", ["**/test_*.py"])
    assert matches_any("test_a.py", ["**/test_*.py"])
    assert matches_any("deep/nested/tests/x.py", ["**/tests/**"])
    assert not matches_any("app.py", ["**/test_*.py"])


def test_validation_never_raises_for_bad_patch(repo: Path) -> None:
    parsed = parse_unified_diff(make_diff("../escape.py"))
    result = validate_patch(parsed, repo)
    assert result.ok is False
