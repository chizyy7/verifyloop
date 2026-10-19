"""Apply parsed patches to a working tree.

Why not shell out to ``git apply``?
-----------------------------------
Small models routinely emit correct hunks with incorrect ``@@`` line numbers. ``git
apply`` rejects those with an opaque message, which destroys the very signal the
evidence-guided strategy depends on. This applier relocates each hunk by exact
context match, refuses ambiguous matches, and reports *why* it failed.

All files are read and written as UTF-8 with ``\\n`` line endings. Benchmark
repositories are LF-only by construction; this is recorded as a limitation for any
future CRLF repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from verifyloop.models import FailureCategory
from verifyloop.patching.parser import Edit, FilePatch, Hunk, ParsedDiff


@dataclass
class ApplyResult:
    ok: bool
    reason: str = ""
    category: FailureCategory = FailureCategory.NONE
    files_changed: list[str] = field(default_factory=list)
    already_applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "category": self.category.value,
            "files_changed": self.files_changed,
            "already_applied": self.already_applied,
        }


def _split(text: str) -> tuple[list[str], bool]:
    """Split into lines without terminators, plus whether a trailing newline exists."""
    if text == "":
        return [], False
    trailing = text.endswith("\n")
    body = text[:-1] if trailing else text
    return body.split("\n"), trailing


def _join(lines: list[str], trailing_newline: bool) -> str:
    if not lines:
        return ""
    text = "\n".join(lines)
    return text + "\n" if trailing_newline else text


def _hunk_blocks(hunk: Hunk) -> tuple[list[str], list[str]]:
    old_block: list[str] = []
    new_block: list[str] = []
    for raw in hunk.lines:
        marker, content = raw[:1], raw[1:]
        if marker == "\\":
            # "\ No newline at end of file" is metadata, not content.
            continue
        if marker == " ":
            old_block.append(content)
            new_block.append(content)
        elif marker == "-":
            old_block.append(content)
        elif marker == "+":
            new_block.append(content)
    return old_block, new_block


def _find_matches(haystack: list[str], needle: list[str]) -> list[int]:
    if not needle:
        return []
    limit = len(haystack) - len(needle)
    if limit < 0:
        return []
    first = needle[0]
    matches: list[int] = []
    for start in range(limit + 1):
        if haystack[start] != first:
            continue
        if haystack[start : start + len(needle)] == needle:
            matches.append(start)
    return matches


def _find_matches_normalized(haystack: list[str], needle: list[str]) -> list[int]:
    """Fallback match ignoring trailing whitespace, used only when exact fails."""
    normalized_needle = [line.rstrip() for line in needle]
    limit = len(haystack) - len(needle)
    if limit < 0:
        return []
    matches: list[int] = []
    for start in range(limit + 1):
        window = [line.rstrip() for line in haystack[start : start + len(needle)]]
        if window == normalized_needle:
            matches.append(start)
    return matches


def apply_unified_diff(parsed: ParsedDiff, repo_root: Path) -> ApplyResult:
    """Apply every file patch atomically; on failure, restore all touched files."""
    originals: dict[Path, str] = {}
    changed: list[str] = []

    try:
        for file_patch in parsed.files:
            target = (repo_root / file_patch.path).resolve()
            try:
                target.relative_to(repo_root.resolve())
            except ValueError:
                return ApplyResult(
                    ok=False,
                    reason=f"path escapes repository: {file_patch.path}",
                    category=FailureCategory.PATCH_PATH,
                )

            if target.exists():
                if target.is_dir():
                    return ApplyResult(
                        ok=False,
                        reason=f"target is a directory: {file_patch.path}",
                        category=FailureCategory.PATCH_PATH,
                    )
                original = target.read_text(encoding="utf-8")
            elif file_patch.is_new:
                original = ""
            else:
                return ApplyResult(
                    ok=False,
                    reason=f"file does not exist: {file_patch.path}",
                    category=FailureCategory.PATCH_CONFLICT,
                )

            originals[target] = original
            updated, error = _apply_file_patch(original, file_patch)
            if error:
                _restore(originals)
                return ApplyResult(
                    ok=False,
                    reason=error,
                    category=FailureCategory.PATCH_CONFLICT,
                )
            if updated != original:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(updated, encoding="utf-8", newline="\n")
                changed.append(file_patch.path)
    except OSError as exc:
        _restore(originals)
        return ApplyResult(
            ok=False,
            reason=f"filesystem error while applying patch: {exc}",
            category=FailureCategory.ENVIRONMENT_ERROR,
        )

    if not changed:
        return ApplyResult(
            ok=False,
            reason="patch produced no file changes (already applied?)",
            category=FailureCategory.PATCH_CONFLICT,
            already_applied=True,
        )
    return ApplyResult(ok=True, files_changed=changed)


def _apply_file_patch(original: str, file_patch: FilePatch) -> tuple[str, str]:
    lines, trailing = _split(original)
    cursor = 0
    offset = 0

    for hunk in file_patch.hunks:
        old_block, new_block = _hunk_blocks(hunk)
        if not old_block:
            if file_patch.is_new:
                # A new-file hunk inserts its content at the start of the file.
                lines[0:0] = new_block
                cursor = len(new_block)
                offset += len(new_block)
                continue
            return original, f"{file_patch.path}: hunk {hunk.header} has no old content"

        search_from = max(0, cursor)
        expected = max(0, hunk.old_start - 1 + offset)
        matches = _find_matches(lines[search_from:], old_block)
        matches = [position + search_from for position in matches]

        if not matches:
            # Retry the whole file, then with whitespace normalization.
            matches = _find_matches(lines, old_block)
            if not matches:
                matches = _find_matches_normalized(lines, old_block)
            if not matches:
                return (
                    original,
                    f"{file_patch.path}: context not found for {hunk.header}",
                )

        if len(matches) > 1:
            # Ambiguous context is dangerous: a model that emits an underspecified
            # hunk could silently edit the wrong function. Only accept the match that
            # lands exactly where the hunk claims to be.
            exact = [position for position in matches if position == expected]
            if len(exact) != 1:
                return (
                    original,
                    f"{file_patch.path}: ambiguous context for {hunk.header} "
                    f"({len(matches)} candidate locations)",
                )
            matches = exact

        position = matches[0]
        lines[position : position + len(old_block)] = new_block
        offset += len(new_block) - len(old_block)
        cursor = position + len(new_block)

    return _join(lines, trailing), ""


def apply_edits(edits: list[Edit], repo_root: Path) -> ApplyResult:
    """Apply ``edit_json`` search/replace edits atomically."""
    originals: dict[Path, str] = {}
    changed: list[str] = []

    try:
        for edit in edits:
            target = (repo_root / edit.file).resolve()
            try:
                target.relative_to(repo_root.resolve())
            except ValueError:
                return ApplyResult(
                    ok=False,
                    reason=f"path escapes repository: {edit.file}",
                    category=FailureCategory.PATCH_PATH,
                )
            if not target.is_file():
                _restore(originals)
                return ApplyResult(
                    ok=False,
                    reason=f"file does not exist: {edit.file}",
                    category=FailureCategory.PATCH_CONFLICT,
                )
            if target not in originals:
                originals[target] = target.read_text(encoding="utf-8")
            current = target.read_text(encoding="utf-8")

            count = current.count(edit.search)
            if count == 0:
                _restore(originals)
                return ApplyResult(
                    ok=False,
                    reason=f"search text not found in {edit.file}",
                    category=FailureCategory.PATCH_CONFLICT,
                )
            if count > 1:
                _restore(originals)
                return ApplyResult(
                    ok=False,
                    reason=(
                        f"search text appears {count} times in {edit.file}; "
                        "it must be unique"
                    ),
                    category=FailureCategory.PATCH_CONFLICT,
                )

            updated = current.replace(edit.search, edit.replace, 1)
            target.write_text(updated, encoding="utf-8", newline="\n")
            if edit.file not in changed:
                changed.append(edit.file)
    except OSError as exc:
        _restore(originals)
        return ApplyResult(
            ok=False,
            reason=f"filesystem error while applying edits: {exc}",
            category=FailureCategory.ENVIRONMENT_ERROR,
        )

    if not changed:
        return ApplyResult(
            ok=False,
            reason="no edits applied",
            category=FailureCategory.PATCH_CONFLICT,
        )
    return ApplyResult(ok=True, files_changed=changed)


def _restore(originals: dict[Path, str]) -> None:
    for path, content in originals.items():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        except OSError:
            # Restoration failure is surfaced by the caller's snapshot comparison.
            pass


def apply_patch(parsed: Any, repo_root: Path) -> ApplyResult:
    """Dispatch to the diff or edit applier based on the parsed payload type."""
    if isinstance(parsed, ParsedDiff):
        return apply_unified_diff(parsed, repo_root)
    return apply_edits(parsed, repo_root)
