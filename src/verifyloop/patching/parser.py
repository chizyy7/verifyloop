"""Extraction and parsing of model-produced patches.

Two accepted formats:

``diff``
    A unified diff, optionally wrapped in a fenced code block and optionally preceded
    by prose. Hunk line numbers may be wrong; the applier re-locates hunks by context.

``edit_json``
    A JSON object ``{"edits": [{"file": ..., "search": ..., "replace": ...}]}``.
    Simpler for small models to produce correctly than a hand-written diff.

Parsing never touches the filesystem, so it is safe to call on untrusted output.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from verifyloop.models import FailureCategory, PatchCandidate


class PatchParseError(ValueError):
    """Raised when model output cannot be interpreted as a patch."""

    def __init__(self, message: str, category: FailureCategory = FailureCategory.PATCH_FORMAT):
        super().__init__(message)
        self.category = category


@dataclass
class Hunk:
    """One unified-diff hunk, with its declared header and line payload."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)  # raw, including leading marker

    @property
    def header(self) -> str:
        return f"@@ -{self.old_start},{self.old_count} +{self.new_start},{self.new_count} @@"


@dataclass
class FilePatch:
    """A change to a single file."""

    old_path: str
    new_path: str
    hunks: list[Hunk] = field(default_factory=list)
    is_new: bool = False
    is_delete: bool = False

    @property
    def path(self) -> str:
        """The repository-relative path this patch targets."""
        candidate = self.new_path if not self.is_delete else self.old_path
        return _normalize_diff_path(candidate)


@dataclass
class ParsedDiff:
    files: list[FilePatch] = field(default_factory=list)

    @property
    def changed_files(self) -> list[str]:
        return sorted({file_patch.path for file_patch in self.files})


@dataclass
class Edit:
    file: str
    search: str
    replace: str


_FENCE_RE = re.compile(r"```(?:diff|patch)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_HUNK_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")
_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$")


def _normalize_diff_path(raw: str) -> str:
    path = raw.strip().strip('"')
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path


def extract_patch_text(raw: str) -> str:
    """Pull the patch body out of a fenced block, or return the raw text."""
    text = raw.strip()
    if not text:
        raise PatchParseError("model returned an empty response")
    matches = _FENCE_RE.findall(text)
    if matches:
        # Prefer the longest fenced block: models sometimes echo the prompt first.
        return max(matches, key=len).strip()
    if text.startswith("diff --git") or text.startswith("--- "):
        return text
    # Tolerate a leading explanation followed by a diff.
    index = text.find("diff --git")
    if index == -1:
        index = text.find("--- ")
    if index != -1:
        return text[index:].strip()
    return text


def looks_like_diff(text: str) -> bool:
    return "diff --git" in text or text.lstrip().startswith("--- ")


def looks_like_json(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("{") and stripped.endswith("}")


# ---------------------------------------------------------------------------
# Unified diff parsing
# ---------------------------------------------------------------------------


def parse_unified_diff(text: str) -> ParsedDiff:
    """Parse a unified diff into structured file patches.

    Raises :class:`PatchParseError` for structurally invalid input. Line-number
    correctness is *not* checked here; the applier handles relocation.
    """
    body = extract_patch_text(text)
    if not body:
        raise PatchParseError("empty patch body")

    lines = body.splitlines()
    files: list[FilePatch] = []
    current: Optional[FilePatch] = None
    current_hunk: Optional[Hunk] = None
    index = 0

    while index < len(lines):
        line = lines[index]

        git_header = _DIFF_HEADER_RE.match(line)
        if git_header:
            if current is not None and current.hunks:
                files.append(current)
            current = FilePatch(
                old_path=git_header.group(1), new_path=git_header.group(2)
            )
            current_hunk = None
            index += 1
            continue

        if line.startswith("--- "):
            old = line[4:].strip()
            # A following +++ line is the normal case; a bare --- means deletion.
            new_line = lines[index + 1] if index + 1 < len(lines) else ""
            if new_line.startswith("+++ "):
                new_path = new_line[4:].strip()
                if current is not None and current.hunks:
                    files.append(current)
                current = FilePatch(
                    old_path=old,
                    new_path=new_path,
                    is_new=old in {"/dev/null", "a//dev/null"},
                    is_delete=new_path in {"/dev/null", "b//dev/null"},
                )
                current_hunk = None
                index += 2
                continue
            raise PatchParseError(f"malformed file header near line {index + 1}")

        hunk_header = _HUNK_RE.match(line)
        if hunk_header:
            if current is None:
                raise PatchParseError(
                    f"hunk header before file header at line {index + 1}"
                )
            current_hunk = Hunk(
                old_start=int(hunk_header.group(1)),
                old_count=int(hunk_header.group(2) or 1),
                new_start=int(hunk_header.group(3)),
                new_count=int(hunk_header.group(4) or 1),
            )
            current.hunks.append(current_hunk)
            index += 1
            continue

        if current_hunk is not None:
            if line.startswith(("+", "-", " ", "\\")):
                current_hunk.lines.append(line)
            elif line == "":
                # Blank lines in a hunk are context lines whose marker was stripped.
                current_hunk.lines.append(" ")
            elif line.startswith("@@"):
                raise PatchParseError(f"unparseable hunk header: {line!r}")
            else:
                # Trailing prose after a hunk ends the hunk.
                current_hunk = None
        index += 1

    if current is not None and current.hunks:
        files.append(current)

    if not files:
        raise PatchParseError("no file changes found in the diff")

    for file_patch in files:
        if not file_patch.hunks:
            raise PatchParseError(f"no hunks for {file_patch.path!r}")
        _validate_hunk_arithmetic(file_patch)

    return ParsedDiff(files=files)


def _validate_hunk_arithmetic(file_patch: FilePatch) -> None:
    """Check that each hunk's declared counts match its payload."""
    for hunk in file_patch.hunks:
        old_seen = sum(1 for line in hunk.lines if line[:1] in {" ", "-"})
        new_seen = sum(1 for line in hunk.lines if line[:1] in {" ", "+"})
        if hunk.old_count != old_seen:
            raise PatchParseError(
                f"{file_patch.path}: hunk {hunk.header} declares {hunk.old_count} "
                f"old lines but contains {old_seen}"
            )
        if hunk.new_count != new_seen:
            raise PatchParseError(
                f"{file_patch.path}: hunk {hunk.header} declares {hunk.new_count} "
                f"new lines but contains {new_seen}"
            )


# ---------------------------------------------------------------------------
# edit_json parsing
# ---------------------------------------------------------------------------


def parse_edit_json(text: str) -> list[Edit]:
    """Parse the ``edit_json`` format into a list of search/replace edits."""
    body = extract_patch_text(text)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PatchParseError(f"edit_json is not valid JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise PatchParseError("edit_json root must be an object")
    raw_edits = payload.get("edits")
    if not isinstance(raw_edits, list) or not raw_edits:
        raise PatchParseError("edit_json requires a non-empty 'edits' list")

    edits: list[Edit] = []
    for position, item in enumerate(raw_edits):
        if not isinstance(item, dict):
            raise PatchParseError(f"edit {position} is not an object")
        missing = {"file", "search", "replace"} - set(item)
        if missing:
            raise PatchParseError(
                f"edit {position} missing keys: {', '.join(sorted(missing))}"
            )
        file_name, search, replace = item["file"], item["search"], item["replace"]
        if not all(isinstance(value, str) for value in (file_name, search, replace)):
            raise PatchParseError(f"edit {position} values must be strings")
        if not search:
            raise PatchParseError(f"edit {position} has an empty search string")
        edits.append(Edit(file=file_name, search=search, replace=replace))
    return edits


def parse_patch(raw: str, patch_format: str = "diff") -> tuple[PatchCandidate, Any]:
    """Parse ``raw`` model output into a candidate plus a format-specific payload.

    Returns ``(candidate, parsed)`` where ``parsed`` is a :class:`ParsedDiff` for
    diffs or ``list[Edit]`` for edit_json.
    """
    if patch_format == "diff":
        parsed = parse_unified_diff(raw)
        changed = parsed.changed_files
    elif patch_format == "edit_json":
        parsed = parse_edit_json(raw)
        changed = sorted({_normalize_diff_path(edit.file) for edit in parsed})
    else:
        raise PatchParseError(f"unsupported patch format: {patch_format}")

    candidate = PatchCandidate(
        raw=raw,
        format=patch_format,
        changed_files=changed,
        size_bytes=len(raw.encode("utf-8")),
    )
    return candidate, parsed


def iter_patch_targets(parsed: Any) -> Iterable[str]:
    """Yield the repository-relative paths a parsed patch would modify."""
    if isinstance(parsed, ParsedDiff):
        for file_patch in parsed.files:
            yield file_patch.path
    else:
        for edit in parsed:
            yield _normalize_diff_path(edit.file)
