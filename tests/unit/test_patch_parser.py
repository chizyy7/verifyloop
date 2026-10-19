"""Tests for patch parsing."""

from __future__ import annotations

import pytest

from verifyloop.patching.parser import (
    PatchParseError,
    extract_patch_text,
    looks_like_diff,
    parse_edit_json,
    parse_patch,
    parse_unified_diff,
)

SIMPLE_DIFF = """--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""


def test_parses_simple_diff() -> None:
    parsed = parse_unified_diff(SIMPLE_DIFF)
    assert len(parsed.files) == 1
    assert parsed.changed_files == ["app.py"]
    hunk = parsed.files[0].hunks[0]
    assert hunk.old_start == 1
    assert hunk.old_count == 2
    assert hunk.new_count == 2


def test_parses_diff_git_header() -> None:
    text = """diff --git a/src/mod.py b/src/mod.py
index 111..222 100644
--- a/src/mod.py
+++ b/src/mod.py
@@ -1,2 +1,2 @@
 x = 1
-y = 2
+y = 3
"""
    parsed = parse_unified_diff(text)
    assert parsed.changed_files == ["src/mod.py"]


def test_extracts_from_fenced_block() -> None:
    wrapped = f"Here is the fix:\n\n```diff\n{SIMPLE_DIFF}```\n\nHope this helps."
    assert "return a + b" in extract_patch_text(wrapped)
    assert looks_like_diff(extract_patch_text(wrapped))


def test_extracts_from_prose_prefix() -> None:
    wrapped = "Sure. The patch is:\n\n" + SIMPLE_DIFF
    parsed = parse_unified_diff(wrapped)
    assert parsed.changed_files == ["app.py"]


def test_rejects_empty_response() -> None:
    with pytest.raises(PatchParseError):
        parse_unified_diff("   ")


def test_rejects_non_diff_text() -> None:
    with pytest.raises(PatchParseError):
        parse_unified_diff("I cannot help with that.")


def test_rejects_hunk_count_mismatch() -> None:
    broken = """--- a/app.py
+++ b/app.py
@@ -1,5 +1,5 @@
 x = 1
-y = 2
+y = 3
"""
    with pytest.raises(PatchParseError, match="declares"):
        parse_unified_diff(broken)


def test_rejects_hunk_before_file_header() -> None:
    with pytest.raises(PatchParseError, match="hunk header before file header"):
        parse_unified_diff("@@ -1,1 +1,1 @@\n-x\n+y\n")


def test_multi_file_diff() -> None:
    text = SIMPLE_DIFF + """--- a/other.py
+++ b/other.py
@@ -1,1 +1,1 @@
-a
+b
"""
    parsed = parse_unified_diff(text)
    assert parsed.changed_files == ["app.py", "other.py"]


def test_edit_json_parsing() -> None:
    text = (
        '{"edits": [{"file": "app.py", "search": "a - b", "replace": "a + b"}]}'
    )
    edits = parse_edit_json(text)
    assert len(edits) == 1
    assert edits[0].file == "app.py"


def test_edit_json_rejects_missing_keys() -> None:
    with pytest.raises(PatchParseError, match="missing keys"):
        parse_edit_json('{"edits": [{"file": "a.py", "search": "x"}]}')


def test_edit_json_rejects_invalid_json() -> None:
    with pytest.raises(PatchParseError, match="not valid JSON"):
        parse_edit_json("{nope}")


def test_edit_json_rejects_empty_edits() -> None:
    with pytest.raises(PatchParseError):
        parse_edit_json('{"edits": []}')


def test_edit_json_rejects_empty_search() -> None:
    with pytest.raises(PatchParseError, match="empty search"):
        parse_edit_json('{"edits": [{"file": "a.py", "search": "", "replace": "x"}]}')


def test_parse_patch_returns_candidate_metadata() -> None:
    candidate, parsed = parse_patch(SIMPLE_DIFF, "diff")
    assert candidate.format == "diff"
    assert candidate.changed_files == ["app.py"]
    assert candidate.size_bytes == len(SIMPLE_DIFF.encode())
    assert len(candidate.sha256) == 64


def test_parse_patch_rejects_unknown_format() -> None:
    with pytest.raises(PatchParseError):
        parse_patch(SIMPLE_DIFF, "yaml")


def test_new_file_diff() -> None:
    text = """--- /dev/null
+++ b/newmod.py
@@ -0,0 +1,2 @@
+x = 1
+y = 2
"""
    parsed = parse_unified_diff(text)
    assert parsed.files[0].is_new
    assert parsed.changed_files == ["newmod.py"]
