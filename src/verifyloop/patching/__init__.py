"""Patch extraction, validation, and application."""

from __future__ import annotations

from verifyloop.patching.applier import ApplyResult, apply_edits, apply_patch, apply_unified_diff
from verifyloop.patching.parser import (
    Edit,
    FilePatch,
    Hunk,
    ParsedDiff,
    PatchParseError,
    extract_patch_text,
    looks_like_diff,
    looks_like_json,
    parse_edit_json,
    parse_patch,
    parse_unified_diff,
)
from verifyloop.patching.validator import (
    ALWAYS_PROTECTED,
    matches_any,
    normalize_repo_path,
    validate_patch,
)

__all__ = [
    "ALWAYS_PROTECTED",
    "ApplyResult",
    "Edit",
    "FilePatch",
    "Hunk",
    "ParsedDiff",
    "PatchParseError",
    "apply_edits",
    "apply_patch",
    "apply_unified_diff",
    "extract_patch_text",
    "looks_like_diff",
    "looks_like_json",
    "matches_any",
    "normalize_repo_path",
    "parse_edit_json",
    "parse_patch",
    "parse_unified_diff",
    "validate_patch",
]
