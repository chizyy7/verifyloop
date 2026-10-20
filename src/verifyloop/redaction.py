"""Bounded secret redaction for diagnostic excerpts.

Collection errors can contain arbitrary text from the repository under test,
including environment-derived values or credentials in a traceback. Evidence sent
back to the model must be useful, but it must not leak unrelated environment data or
secret material. This module intentionally does two things only:

* redact values whose environment-variable names look secret-bearing;
* redact common credential shapes (API keys, bearer tokens, basic-auth URLs,
  ``key=value`` pairs).

It is a defensive filter, not a guarantee. Callers must still bound the amount of
text they pass through it.
"""

from __future__ import annotations

import os
import re
from typing import Mapping, Optional

REDACTED = "***redacted***"

_SECRET_ENV_NAME_RE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?key|secret|token|password|passwd|"
    r"authorization|credential|private[_-]?key)"
)

_KEY_VALUE_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?key|secret|token|password|passwd|"
    r"authorization|credential|private[_-]?key)\b"
    r"(\s*[:=]\s*)"
    r"(['\"]?)"
    r"([^\s'\",;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_GITHUB_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")
_AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_BASIC_AUTH_RE = re.compile(r"(https?://)([^/\s:@]+):([^/\s@]+)@")


def _redact_key_value(match: re.Match[str]) -> str:
    return f"{match.group(1)}{match.group(2)}{match.group(3)}{REDACTED}{match.group(3)}"


def redact_text(text: str, *, environ: Optional[Mapping[str, str]] = None) -> str:
    """Redact likely secrets from ``text`` while preserving surrounding context."""
    if not text:
        return ""

    env = os.environ if environ is None else environ
    for name, value in env.items():
        # Short values cause accidental substring replacements in ordinary code.
        if not value or len(value) < 6:
            continue
        if _SECRET_ENV_NAME_RE.search(name):
            text = text.replace(value, REDACTED)

    # Bearer tokens must be removed before the generic key/value rule, which would
    # otherwise match the word "Bearer" and leave the token itself untouched.
    text = _BEARER_RE.sub(f"Bearer {REDACTED}", text)
    text = _KEY_VALUE_RE.sub(_redact_key_value, text)
    text = _SK_RE.sub(REDACTED, text)
    text = _GITHUB_RE.sub(REDACTED, text)
    text = _AWS_KEY_RE.sub(REDACTED, text)
    text = _BASIC_AUTH_RE.sub(rf"\1{REDACTED}@", text)
    return text
