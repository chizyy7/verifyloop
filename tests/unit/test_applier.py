"""Tests for patch application, including hunk relocation and atomic rollback."""

from __future__ import annotations

from pathlib import Path

import pytest

from verifyloop.patching.applier import apply_edits, apply_patch, apply_unified_diff
from verifyloop.patching.parser import Edit, parse_edit_json, parse_unified_diff


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(
        "def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n",
        encoding="utf-8",
    )
    return tmp_path


def test_applies_simple_diff(repo: Path) -> None:
    text = """--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""
    result = apply_unified_diff(parse_unified_diff(text), repo)
    assert result.ok
    assert "return a + b" in (repo / "app.py").read_text(encoding="utf-8")


def test_relocates_hunk_with_wrong_line_numbers(repo: Path) -> None:
    # Hunk claims line 40; the content is actually at line 5.
    text = """--- a/app.py
+++ b/app.py
@@ -40,2 +40,2 @@
 def mul(a, b):
-    return a * b
+    return a * b * 1
"""
    result = apply_unified_diff(parse_unified_diff(text), repo)
    assert result.ok
    assert "a * b * 1" in (repo / "app.py").read_text(encoding="utf-8")


def test_reports_missing_context(repo: Path) -> None:
    text = """--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-this line does not exist
+replacement
"""
    result = apply_unified_diff(parse_unified_diff(text), repo)
    assert not result.ok
    assert "context not found" in result.reason
    assert result.category.value == "patch_conflict"


def test_missing_file_rejected(repo: Path) -> None:
    text = """--- a/absent.py
+++ b/absent.py
@@ -1,1 +1,1 @@
-x = 1
+x = 2
"""
    result = apply_unified_diff(parse_unified_diff(text), repo)
    assert not result.ok
    assert "does not exist" in result.reason


def test_atomic_rollback_on_second_file_failure(repo: Path) -> None:
    (repo / "other.py").write_text("y = 1\n", encoding="utf-8")
    text = """--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
--- a/other.py
+++ b/other.py
@@ -1,1 +1,1 @@
-nonexistent content
+replacement
"""
    before = (repo / "app.py").read_text(encoding="utf-8")
    result = apply_unified_diff(parse_unified_diff(text), repo)
    assert not result.ok
    assert (repo / "app.py").read_text(encoding="utf-8") == before


def test_creates_new_file(repo: Path) -> None:
    text = """--- /dev/null
+++ b/helper.py
@@ -0,0 +1,2 @@
+def helper():
+    return 1
"""
    result = apply_unified_diff(parse_unified_diff(text), repo)
    assert result.ok
    assert (repo / "helper.py").is_file()


def test_no_op_patch_rejected(repo: Path) -> None:
    text = """--- a/app.py
+++ b/app.py
@@ -1,1 +1,1 @@
-def add(a, b):
+def add(a, b):
"""
    result = apply_unified_diff(parse_unified_diff(text), repo)
    assert not result.ok
    assert result.already_applied


def test_edit_json_application(repo: Path) -> None:
    edits = [
        Edit(file="app.py", search="return a - b", replace="return a + b"),
    ]
    result = apply_edits(edits, repo)
    assert result.ok
    assert "return a + b" in (repo / "app.py").read_text(encoding="utf-8")


def test_edit_json_requires_unique_search(repo: Path) -> None:
    (repo / "dup.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    edits = [Edit(file="dup.py", search="x = 1", replace="x = 2")]
    result = apply_edits(edits, repo)
    assert not result.ok
    assert "appears 2 times" in result.reason


def test_edit_json_missing_search_text(repo: Path) -> None:
    edits = [Edit(file="app.py", search="not present", replace="x")]
    result = apply_edits(edits, repo)
    assert not result.ok
    assert "not found" in result.reason


def test_edit_json_path_escape_rejected(repo: Path) -> None:
    edits = [Edit(file="../outside.py", search="a", replace="b")]
    result = apply_edits(edits, repo)
    assert not result.ok
    assert "escapes" in result.reason


def test_apply_patch_dispatches(repo: Path) -> None:
    edits = parse_edit_json(
        '{"edits": [{"file": "app.py", "search": "return a - b", "replace": "return a + b"}]}'
    )
    assert apply_patch(edits, repo).ok


def test_ambiguous_context_rejected(tmp_path: Path) -> None:
    (tmp_path / "dup.py").write_text(
        "def f():\n    return 1\n\ndef g():\n    return 1\n", encoding="utf-8"
    )
    text = """--- a/dup.py
+++ b/dup.py
@@ -1,2 +1,2 @@
 def f():
-    return 1
+    return 2
"""
    # The two-line context is unique because of the def line, so this should succeed.
    result = apply_unified_diff(parse_unified_diff(text), tmp_path)
    assert result.ok
    assert "return 2" in (tmp_path / "dup.py").read_text(encoding="utf-8")

    # Restore the duplicate content for a genuinely ambiguous single-line hunk.
    (tmp_path / "dup.py").write_text(
        "def f():\n    return 1\n\ndef g():\n    return 1\n", encoding="utf-8"
    )
    ambiguous = """--- a/dup.py
+++ b/dup.py
@@ -1,1 +1,1 @@
-    return 1
+    return 3
"""
    result = apply_unified_diff(parse_unified_diff(ambiguous), tmp_path)
    assert not result.ok
    assert "ambiguous" in result.reason
    assert "return 1" in (tmp_path / "dup.py").read_text(encoding="utf-8")
