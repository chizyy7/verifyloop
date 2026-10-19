"""Generate the VerifyLoop synthetic benchmark corpus (v1).

Why a generator?
----------------
Each task needs four synchronized artifacts: the buggy repository, visible feedback
tests, hidden evaluation tests, and a reference patch. Hand-editing four copies invites
drift. This script is the single source of truth: it writes the corpus and derives the
reference patch with ``difflib`` so the patch is guaranteed to apply to the shipped code.

Every defect is deliberately seeded. These are synthetic tasks, not production incidents.

Usage:
    python scripts/build_benchmark.py            # write/refresh the corpus
    python scripts/build_benchmark.py --check    # verify the corpus is in sync
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = REPO_ROOT / "benchmarks" / "synthetic" / "v1"
BENCHMARK_VERSION = "v1"

CONFTEST = '''"""Make the repository root importable when pytest runs from anywhere."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
'''

TASKS: list[dict[str, Any]] = [
    {
        "id": "boundary_paginate_001",
        "title": "Pagination drops the last item of every page",
        "category": "boundary_condition",
        "difficulty": "easy",
        "description": (
            "The paginate() helper in paging.py is used by the reporting service to slice "
            "records into pages. Users report that every page is missing its final record: "
            "page 1 of 10 items with per_page=3 returns only 2 items. Fix paginate() so that "
            "a full page contains per_page items, a partial final page returns the remainder, "
            "and out-of-range pages return an empty list. Keep the existing validation that "
            "page and per_page must be >= 1."
        ),
        "expected_behavior": (
            "paginate(range(10), 1, 3) == [0, 1, 2]; paginate(range(10), 4, 3) == [9]; "
            "paginate(range(10), 9, 3) == []. Validation errors unchanged."
        ),
        "files": {
            "paging.py": '''"""Pagination helpers for the reporting service."""


def paginate(items, page, per_page):
    """Return one page of ``items``.

    ``page`` is 1-based. A page holds at most ``per_page`` items.
    """
    if page < 1:
        raise ValueError("page must be >= 1")
    if per_page < 1:
        raise ValueError("per_page must be >= 1")
    start = (page - 1) * per_page
    end = start + per_page - 1
    return list(items[start:end])
''',
            "tests/test_paging.py": '''import pytest

from paging import paginate


def test_first_page_has_full_page():
    assert paginate(list(range(10)), 1, 3) == [0, 1, 2]


def test_second_page_continues():
    assert paginate(list(range(10)), 2, 3) == [3, 4, 5]


def test_invalid_page_rejected():
    with pytest.raises(ValueError):
        paginate([1, 2, 3], 0, 2)


def test_invalid_per_page_rejected():
    with pytest.raises(ValueError):
        paginate([1, 2, 3], 1, 0)
''',
        },
        "fixed": {
            "paging.py": '''"""Pagination helpers for the reporting service."""


def paginate(items, page, per_page):
    """Return one page of ``items``.

    ``page`` is 1-based. A page holds at most ``per_page`` items.
    """
    if page < 1:
        raise ValueError("page must be >= 1")
    if per_page < 1:
        raise ValueError("per_page must be >= 1")
    items = list(items)
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end]
''',
        },
        "eval_tests": {
            "test_eval_paging.py": '''import pytest

from paging import paginate


def test_last_partial_page():
    assert paginate(list(range(10)), 4, 3) == [9]


def test_out_of_range_page_is_empty():
    assert paginate(list(range(10)), 9, 3) == []


def test_per_page_one():
    assert paginate(["a", "b", "c"], 2, 1) == ["b"]


def test_no_items_lost_across_pages():
    items = list(range(17))
    collected = []
    for page in range(1, 8):
        collected.extend(paginate(items, page, 3))
    assert collected == items


def test_accepts_iterators():
    assert paginate(iter(range(5)), 1, 2) == [0, 1]


def test_validation_errors_preserved():
    with pytest.raises(ValueError):
        paginate([], 0, 1)
    with pytest.raises(ValueError):
        paginate([], 1, -1)
''',
        },
    },
    {
        "id": "boundary_stats_002",
        "title": "Statistics helpers fail on empty and even-length input",
        "category": "boundary_condition",
        "difficulty": "medium",
        "description": (
            "The analytics module (stats.py) exposes mean() and median(). Two defects are "
            "reported. First, both functions raise an implementation-level error on an empty "
            "sequence instead of a ValueError with a clear message. Second, median() returns "
            "the upper middle element for even-length sequences instead of the average of the "
            "two middle elements. Fix both while keeping the functions pure."
        ),
        "expected_behavior": (
            "mean([]) and median([]) raise ValueError. median([1, 2, 3, 4]) == 2.5. "
            "Odd-length medians and normal means are unchanged."
        ),
        "files": {
            "stats.py": '''"""Small descriptive statistics helpers."""


def mean(values):
    """Arithmetic mean of a non-empty sequence."""
    return sum(values) / len(values)


def median(values):
    """Median of a non-empty sequence."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle]
''',
            "tests/test_stats.py": '''import pytest

from stats import mean, median


def test_mean_basic():
    assert mean([1, 2, 3, 4]) == 2.5


def test_median_odd():
    assert median([5, 1, 3]) == 3


def test_empty_mean_rejected():
    with pytest.raises(ValueError):
        mean([])


def test_empty_median_rejected():
    with pytest.raises(ValueError):
        median([])
''',
        },
        "fixed": {
            "stats.py": '''"""Small descriptive statistics helpers."""


def mean(values):
    """Arithmetic mean of a non-empty sequence."""
    values = list(values)
    if not values:
        raise ValueError("mean requires at least one value")
    return sum(values) / len(values)


def median(values):
    """Median of a non-empty sequence."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("median requires at least one value")
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2
''',
        },
        "eval_tests": {
            "test_eval_stats.py": '''import pytest

from stats import mean, median


def test_even_median_averages_middle_pair():
    assert median([1, 2, 3, 4]) == 2.5
    assert median([4, 3, 2, 1]) == 2.5


def test_even_median_two_elements():
    assert median([10, 20]) == 15


def test_single_element():
    assert mean([7]) == 7
    assert median([7]) == 7


def test_empty_errors_are_value_errors():
    with pytest.raises(ValueError):
        mean([])
    with pytest.raises(ValueError):
        median([])


def test_accepts_generators():
    assert mean(x for x in [2, 4, 6]) == 4
    assert median(x for x in [1, 2, 3, 4]) == 2.5


def test_does_not_mutate_input():
    data = [3, 1, 2]
    median(data)
    assert data == [3, 1, 2]
''',
        },
    },
    {
        "id": "boundary_binary_015",
        "title": "Binary search returns an arbitrary duplicate index",
        "category": "boundary_condition",
        "difficulty": "medium",
        "description": (
            "search.py implements binary_search over a sorted list. The function currently "
            "returns whichever matching index the midpoint lands on, but its documented "
            "contract requires the index of the *first* occurrence of the target. Fix the "
            "implementation so it returns the first index, keeps returning -1 for missing "
            "values, and remains O(log n)."
        ),
        "expected_behavior": (
            "binary_search([1, 2, 2, 2, 3], 2) == 1; binary_search([], 1) == -1; "
            "binary_search([1, 3, 5], 4) == -1."
        ),
        "files": {
            "search.py": '''"""Search helpers used by the index builder."""


def binary_search(items, target):
    """Return the index of ``target`` in the sorted sequence ``items``.

    Returns -1 when the target is absent. When duplicates exist, the index of the
    first occurrence is required.
    """
    low, high = 0, len(items) - 1
    while low <= high:
        middle = (low + high) // 2
        if items[middle] == target:
            return middle
        if items[middle] < target:
            low = middle + 1
        else:
            high = middle - 1
    return -1
''',
            "tests/test_search.py": '''from search import binary_search


def test_finds_present_value():
    assert binary_search([1, 3, 5, 7], 5) == 2


def test_missing_value():
    assert binary_search([1, 3, 5, 7], 4) == -1


def test_empty_sequence():
    assert binary_search([], 1) == -1


def test_returns_first_duplicate():
    assert binary_search([1, 2, 2, 2, 3], 2) == 1
''',
        },
        "fixed": {
            "search.py": '''"""Search helpers used by the index builder."""


def binary_search(items, target):
    """Return the index of ``target`` in the sorted sequence ``items``.

    Returns -1 when the target is absent. When duplicates exist, the index of the
    first occurrence is required.
    """
    low, high = 0, len(items) - 1
    found = -1
    while low <= high:
        middle = (low + high) // 2
        if items[middle] == target:
            found = middle
            high = middle - 1
        elif items[middle] < target:
            low = middle + 1
        else:
            high = middle - 1
    return found
''',
        },
        "eval_tests": {
            "test_eval_search.py": '''from search import binary_search


def test_returns_first_duplicate():
    assert binary_search([1, 2, 2, 2, 3], 2) == 1
    assert binary_search([0, 0, 0], 0) == 0
    assert binary_search([1, 1, 2, 2], 2) == 2


def test_last_duplicate_region():
    assert binary_search([1, 2, 3, 3, 3], 3) == 2


def test_single_element():
    assert binary_search([42], 42) == 0
    assert binary_search([42], 7) == -1


def test_large_sequence_is_logarithmic():
    items = list(range(10000))
    assert binary_search(items, 9999) == 9999
    assert binary_search(items, 5000) == 5000
    assert binary_search(items, -1) == -1
''',
        },
    },
    {
        "id": "validation_age_003",
        "title": "Age validation accepts impossible values",
        "category": "input_validation",
        "difficulty": "easy",
        "description": (
            "validation.py validates a user's age before persistence. It currently rejects "
            "ages above 150 but accepts negative ages, and it also accepts booleans because "
            "bool is a subclass of int. Fix validate_age() so it accepts integers in the "
            "inclusive range 0..150, rejects booleans with TypeError, and keeps raising "
            "ValueError for out-of-range numbers."
        ),
        "expected_behavior": (
            "validate_age(0) == 0 and validate_age(150) == 150. validate_age(-1) and "
            "validate_age(151) raise ValueError. validate_age(True) raises TypeError."
        ),
        "files": {
            "validation.py": '''"""Input validation for the user profile service."""


def validate_age(value):
    """Return a validated age, or raise on invalid input."""
    if not isinstance(value, int):
        raise TypeError("age must be an int")
    if value > 150:
        raise ValueError("age must be between 0 and 150")
    return value
''',
            "tests/test_validation.py": '''import pytest

from validation import validate_age


def test_typical_age():
    assert validate_age(30) == 30


def test_too_old_rejected():
    with pytest.raises(ValueError):
        validate_age(151)


def test_negative_age_rejected():
    with pytest.raises(ValueError):
        validate_age(-1)


def test_non_integer_rejected():
    with pytest.raises(TypeError):
        validate_age("30")
''',
        },
        "fixed": {
            "validation.py": '''"""Input validation for the user profile service."""


def validate_age(value):
    """Return a validated age, or raise on invalid input."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("age must be an int")
    if value < 0 or value > 150:
        raise ValueError("age must be between 0 and 150")
    return value
''',
        },
        "eval_tests": {
            "test_eval_validation.py": '''import pytest

from validation import validate_age


def test_lower_boundary_inclusive():
    assert validate_age(0) == 0


def test_upper_boundary_inclusive():
    assert validate_age(150) == 150


def test_negative_rejected():
    with pytest.raises(ValueError):
        validate_age(-1)
    with pytest.raises(ValueError):
        validate_age(-100)


def test_boolean_rejected():
    with pytest.raises(TypeError):
        validate_age(True)
    with pytest.raises(TypeError):
        validate_age(False)


def test_float_rejected():
    with pytest.raises(TypeError):
        validate_age(30.0)


def test_just_inside_bounds():
    assert validate_age(1) == 1
    assert validate_age(149) == 149
''',
        },
    },
    {
        "id": "validation_email_004",
        "title": "Contact parser rejects valid email addresses",
        "category": "input_validation",
        "difficulty": "medium",
        "description": (
            "contacts.py parses 'Name <email>' strings. The current email check only allows "
            "lowercase letters and a single dot, so addresses containing digits, dots in the "
            "local part, or a plus tag are wrongly rejected. Fix parse_contact() so it accepts "
            "common valid addresses (letters, digits, dots, underscores, plus tags, hyphens in "
            "the domain), still rejects strings without an @ or with no dot in the domain, and "
            "keeps raising ValueError for malformed input."
        ),
        "expected_behavior": (
            "parse_contact('Ada <ada+research@example.co.uk>') returns the name and address; "
            "parse_contact('bad-address') raises ValueError."
        ),
        "files": {
            "contacts.py": '''"""Contact string parsing."""

import re

EMAIL_RE = re.compile(r"^[a-z]+@[a-z]+\\.[a-z]+$")


def parse_contact(text):
    """Parse ``"Name <email>"`` into ``(name, email)``."""
    if "<" not in text or not text.endswith(">"):
        raise ValueError("expected format: Name <email>")
    name, _, rest = text.partition("<")
    email = rest[:-1].strip()
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")
    if not EMAIL_RE.match(email):
        raise ValueError("invalid email address: %s" % email)
    return name, email
''',
            "tests/test_contacts.py": '''import pytest

from contacts import parse_contact


def test_simple_contact():
    assert parse_contact("Ada <ada@example.com>") == ("Ada", "ada@example.com")


def test_plus_tag_accepted():
    assert parse_contact("Ada <ada+research@example.com>")[1] == "ada+research@example.com"


def test_missing_brackets_rejected():
    with pytest.raises(ValueError):
        parse_contact("ada@example.com")


def test_missing_at_rejected():
    with pytest.raises(ValueError):
        parse_contact("Ada <ada.example.com>")
''',
        },
        "fixed": {
            "contacts.py": '''"""Contact string parsing."""

import re

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)+$")


def parse_contact(text):
    """Parse ``"Name <email>"`` into ``(name, email)``."""
    if "<" not in text or not text.endswith(">"):
        raise ValueError("expected format: Name <email>")
    name, _, rest = text.partition("<")
    email = rest[:-1].strip()
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")
    if not EMAIL_RE.match(email):
        raise ValueError("invalid email address: %s" % email)
    return name, email
''',
        },
        "eval_tests": {
            "test_eval_contacts.py": '''import pytest

from contacts import parse_contact


def test_plus_tag_accepted():
    assert parse_contact("Ada <ada+research@example.com>") == (
        "Ada",
        "ada+research@example.com",
    )


def test_digits_and_dots_accepted():
    name, email = parse_contact("Grace <grace.m.hopper2@navy.mil>")
    assert name == "Grace"
    assert email == "grace.m.hopper2@navy.mil"


def test_multi_level_domain_accepted():
    assert parse_contact("Alan <alan@math.example.co.uk>")[1] == "alan@math.example.co.uk"


def test_hyphenated_domain_accepted():
    assert parse_contact("Linus <linus@kernel-archive.org>")[1] == "linus@kernel-archive.org"


def test_domain_without_dot_rejected():
    with pytest.raises(ValueError):
        parse_contact("Ada <ada@localhost>")


def test_empty_name_rejected():
    with pytest.raises(ValueError):
        parse_contact(" <ada@example.com>")
''',
        },
    },
    {
        "id": "validation_csv_016",
        "title": "CSV line parser breaks on quoted commas",
        "category": "input_validation",
        "difficulty": "medium",
        "description": (
            "ingest.py parses a single CSV line with str.split(','). Fields that contain a "
            "comma inside double quotes are therefore split incorrectly, and quoted fields "
            "keep their surrounding quotes. Replace the manual split with Python's csv module "
            "so quoted commas and doubled quotes are handled correctly, while plain lines keep "
            "working."
        ),
        "expected_behavior": (
            "parse_csv_line('a,b,c') == ['a', 'b', 'c']; "
            "parse_csv_line('a,\"b,c\",d') == ['a', 'b,c', 'd']; "
            "parse_csv_line('a,\"say \"\"hi\"\"\",b') == ['a', 'say \"hi\"', 'b']."
        ),
        "files": {
            "ingest.py": '''"""Line-oriented CSV ingestion."""


def parse_csv_line(line):
    """Split one CSV line into fields."""
    return line.split(",")
''',
            "tests/test_ingest.py": '''from ingest import parse_csv_line


def test_plain_line():
    assert parse_csv_line("a,b,c") == ["a", "b", "c"]


def test_single_field():
    assert parse_csv_line("only") == ["only"]


def test_empty_line():
    assert parse_csv_line("") == []


def test_quoted_comma():
    assert parse_csv_line('a,"b,c",d') == ["a", "b,c", "d"]
''',
        },
        "fixed": {
            "ingest.py": '''"""Line-oriented CSV ingestion."""

import csv


def parse_csv_line(line):
    """Split one CSV line into fields."""
    return next(csv.reader([line]))
''',
        },
        "eval_tests": {
            "test_eval_ingest.py": '''from ingest import parse_csv_line


def test_quoted_comma():
    assert parse_csv_line('a,"b,c",d') == ["a", "b,c", "d"]


def test_escaped_quotes():
    assert parse_csv_line('a,"say ""hi""",b') == ["a", 'say "hi"', "b"]


def test_empty_fields_preserved():
    assert parse_csv_line("a,,c") == ["a", "", "c"]


def test_trailing_comma():
    assert parse_csv_line("a,b,") == ["a", "b", ""]


def test_quoted_newline_free_text():
    assert parse_csv_line('"one,two",three') == ["one,two", "three"]
''',
        },
    },
    {
        "id": "exception_json_005",
        "title": "JSON loader swallows every error",
        "category": "exception_handling",
        "difficulty": "medium",
        "description": (
            "storage.py contains load_json(), which wraps the whole read in 'except Exception' "
            "and returns the default value. This hides corrupted files and programming errors. "
            "Fix it so that only a missing file returns the default; malformed JSON raises "
            "ValueError with the original exception chained; and other OSError conditions "
            "propagate unchanged."
        ),
        "expected_behavior": (
            "Missing path returns default. Valid JSON returns parsed data. Invalid JSON raises "
            "ValueError. Permission errors are not converted to the default."
        ),
        "files": {
            "storage.py": '''"""JSON file helpers."""

import json


def load_json(path, default=None):
    """Load JSON from ``path``, returning ``default`` when it cannot be read."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default
''',
            "tests/test_storage.py": '''import json

import pytest

from storage import load_json


def test_reads_valid_file(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert load_json(path) == {"a": 1}


def test_missing_file_returns_default(tmp_path):
    assert load_json(tmp_path / "absent.json", default={"fallback": True}) == {
        "fallback": True
    }


def test_malformed_json_raises(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_json(path)
''',
        },
        "fixed": {
            "storage.py": '''"""JSON file helpers."""

import json


def load_json(path, default=None):
    """Load JSON from ``path``.

    A missing file returns ``default``. Malformed JSON raises ``ValueError``. Other
    OS-level failures propagate so callers can distinguish corruption from absence.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise ValueError("invalid JSON in %s" % path) from exc
''',
        },
        "eval_tests": {
            "test_eval_storage.py": '''import json

import pytest

from storage import load_json


def test_malformed_json_raises_value_error(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_json(path, default={})


def test_malformed_json_chains_original(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_json(path)
    assert excinfo.value.__cause__ is not None


def test_missing_file_returns_none_by_default(tmp_path):
    assert load_json(tmp_path / "nope.json") is None


def test_directory_path_is_not_swallowed(tmp_path):
    with pytest.raises(OSError):
        load_json(tmp_path)


def test_nested_structures_round_trip(tmp_path):
    payload = {"users": [{"id": 1, "tags": ["a", "b"]}], "ok": True}
    path = tmp_path / "nested.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_json(path) == payload


def test_default_not_returned_for_bad_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("[]]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_json(path, default={"sentinel": 1})
''',
        },
    },
    {
        "id": "exception_retry_006",
        "title": "Retry decorator performs one attempt too few",
        "category": "exception_handling",
        "difficulty": "medium",
        "description": (
            "resilience.py provides a retry decorator. Its docstring states that ``times`` is "
            "the total number of attempts, but the loop currently runs one attempt fewer than "
            "requested, so retry(times=1) never calls the function at all and retry(times=3) "
            "only makes two attempts. Fix the loop, preserve the behaviour that the last "
            "exception is re-raised when all attempts fail, and keep non-matching exceptions "
            "propagating immediately."
        ),
        "expected_behavior": (
            "A function failing twice then succeeding succeeds under times=3 and is called 3 "
            "times. A function always raising is called exactly times times and the original "
            "exception type is raised."
        ),
        "files": {
            "resilience.py": '''"""Retry helpers."""

from functools import wraps


def retry(times, exceptions=(Exception,)):
    """Retry ``times`` total attempts when one of ``exceptions`` is raised."""
    if times < 1:
        raise ValueError("times must be >= 1")

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for _ in range(times - 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_error = exc
            raise last_error

        return wrapper

    return decorator
''',
            "tests/test_resilience.py": '''import pytest

from resilience import retry


def test_success_passes_through():
    @retry(times=3)
    def ok():
        return "value"

    assert ok() == "value"


def test_invalid_times_rejected():
    with pytest.raises(ValueError):
        retry(times=0)


def test_single_attempt_is_made():
    calls = []

    @retry(times=1)
    def flaky():
        calls.append(1)
        raise RuntimeError("always")

    with pytest.raises(RuntimeError):
        flaky()
    assert len(calls) == 1


def test_non_matching_exception_propagates():
    @retry(times=3, exceptions=(ValueError,))
    def boom():
        raise KeyError("nope")

    with pytest.raises(KeyError):
        boom()
''',
        },
        "fixed": {
            "resilience.py": '''"""Retry helpers."""

from functools import wraps


def retry(times, exceptions=(Exception,)):
    """Retry ``times`` total attempts when one of ``exceptions`` is raised."""
    if times < 1:
        raise ValueError("times must be >= 1")

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for _ in range(times):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_error = exc
            raise last_error

        return wrapper

    return decorator
''',
        },
        "eval_tests": {
            "test_eval_resilience.py": '''import pytest

from resilience import retry


def test_single_attempt_still_calls_once():
    calls = []

    @retry(times=1)
    def flaky():
        calls.append(1)
        raise RuntimeError("always")

    with pytest.raises(RuntimeError):
        flaky()
    assert len(calls) == 1


def test_recovers_on_third_attempt():
    calls = []

    @retry(times=3)
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("not yet")
        return "done"

    assert flaky() == "done"
    assert len(calls) == 3


def test_exhausts_exactly_times_attempts():
    calls = []

    @retry(times=4)
    def always_fails():
        calls.append(1)
        raise ValueError("nope")

    with pytest.raises(ValueError):
        always_fails()
    assert len(calls) == 4


def test_preserves_metadata():
    @retry(times=2)
    def documented():
        """Docstring."""

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Docstring."


def test_arguments_forwarded():
    @retry(times=2)
    def add(a, b=0):
        return a + b

    assert add(2, b=5) == 7
''',
        },
    },
    {
        "id": "sorting_records_007",
        "title": "Descending sort also reverses the tie-breaker",
        "category": "sorting_filtering",
        "difficulty": "easy",
        "description": (
            "ranking.py sorts score records for a leaderboard. The intended order is score "
            "descending, and ties must be broken by name ascending. The current implementation "
            "puts both fields in one tuple key and reverses the whole tuple, so tied names come "
            "out descending as well. Fix the ordering while keeping the function pure and "
            "stable."
        ),
        "expected_behavior": (
            "sort_records([{'name': 'b', 'score': 10}, {'name': 'a', 'score': 10}]) "
            "returns a before b; higher scores always come first."
        ),
        "files": {
            "ranking.py": '''"""Leaderboard ordering."""


def sort_records(records, key="score", descending=True):
    """Return records ordered by ``key`` with name as the tie-breaker."""
    return sorted(records, key=lambda record: (record[key], record["name"]), reverse=descending)
''',
            "tests/test_ranking.py": '''from ranking import sort_records


def test_highest_score_first():
    records = [
        {"name": "a", "score": 1},
        {"name": "b", "score": 9},
        {"name": "c", "score": 5},
    ]
    assert [r["name"] for r in sort_records(records)] == ["b", "c", "a"]


def test_ascending_mode():
    records = [{"name": "a", "score": 2}, {"name": "b", "score": 1}]
    assert [r["name"] for r in sort_records(records, descending=False)] == ["b", "a"]


def test_ties_break_by_name_ascending():
    records = [
        {"name": "zeta", "score": 10},
        {"name": "alpha", "score": 10},
    ]
    assert [r["name"] for r in sort_records(records)] == ["alpha", "zeta"]
''',
        },
        "fixed": {
            "ranking.py": '''"""Leaderboard ordering."""


def sort_records(records, key="score", descending=True):
    """Return records ordered by ``key`` with name as the tie-breaker."""
    by_name = sorted(records, key=lambda record: record["name"])
    return sorted(by_name, key=lambda record: record[key], reverse=descending)
''',
        },
        "eval_tests": {
            "test_eval_ranking.py": '''from ranking import sort_records


def test_ties_break_by_name_ascending():
    records = [
        {"name": "zeta", "score": 10},
        {"name": "alpha", "score": 10},
        {"name": "mike", "score": 10},
    ]
    assert [r["name"] for r in sort_records(records)] == ["alpha", "mike", "zeta"]


def test_ties_ascending_mode_still_name_ascending():
    records = [
        {"name": "beta", "score": 1},
        {"name": "alpha", "score": 1},
    ]
    assert [r["name"] for r in sort_records(records, descending=False)] == ["alpha", "beta"]


def test_input_not_mutated():
    records = [{"name": "b", "score": 1}, {"name": "a", "score": 2}]
    original = [dict(r) for r in records]
    sort_records(records)
    assert records == original


def test_custom_key():
    records = [{"name": "a", "wins": 2}, {"name": "b", "wins": 7}]
    assert [r["name"] for r in sort_records(records, key="wins")] == ["b", "a"]


def test_empty_and_single():
    assert sort_records([]) == []
    assert sort_records([{"name": "only", "score": 1}]) == [{"name": "only", "score": 1}]
''',
        },
    },
    {
        "id": "filtering_score_008",
        "title": "Score filter excludes the boundary and crashes on missing data",
        "category": "sorting_filtering",
        "difficulty": "medium",
        "description": (
            "reports.py filters records by a minimum score. Two defects are reported: the "
            "comparison uses > so records exactly at the threshold are dropped, and records "
            "without a usable numeric score raise KeyError or TypeError instead of being "
            "skipped. Fix filter_by_score() so the threshold is inclusive and records with a "
            "missing or non-numeric score are excluded without raising."
        ),
        "expected_behavior": (
            "filter_by_score([{'score': 5}], 5) keeps the record. Records with no 'score' key, "
            "None, or a string are skipped. Order is preserved."
        ),
        "files": {
            "reports.py": '''"""Report filtering helpers."""


def filter_by_score(records, minimum):
    """Return records whose score is at least ``minimum``."""
    return [record for record in records if record["score"] > minimum]
''',
            "tests/test_reports.py": '''from reports import filter_by_score


def test_above_threshold_kept():
    records = [{"id": 1, "score": 8}, {"id": 2, "score": 3}]
    assert [r["id"] for r in filter_by_score(records, 5)] == [1]


def test_threshold_is_inclusive():
    records = [{"id": 1, "score": 5}, {"id": 2, "score": 4}]
    assert [r["id"] for r in filter_by_score(records, 5)] == [1]


def test_empty_input():
    assert filter_by_score([], 5) == []
''',
        },
        "fixed": {
            "reports.py": '''"""Report filtering helpers."""


def filter_by_score(records, minimum):
    """Return records whose score is at least ``minimum``."""
    selected = []
    for record in records:
        score = record.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue
        if score >= minimum:
            selected.append(record)
    return selected
''',
        },
        "eval_tests": {
            "test_eval_reports.py": '''from reports import filter_by_score


def test_threshold_is_inclusive():
    records = [{"id": 1, "score": 5}, {"id": 2, "score": 4}]
    assert [r["id"] for r in filter_by_score(records, 5)] == [1]


def test_missing_score_skipped():
    records = [{"id": 1}, {"id": 2, "score": 9}]
    assert [r["id"] for r in filter_by_score(records, 0)] == [2]


def test_none_score_skipped():
    records = [{"id": 1, "score": None}, {"id": 2, "score": 3}]
    assert [r["id"] for r in filter_by_score(records, 0)] == [2]


def test_string_score_skipped():
    records = [{"id": 1, "score": "9"}, {"id": 2, "score": 3}]
    assert [r["id"] for r in filter_by_score(records, 0)] == [2]


def test_order_preserved():
    records = [{"id": i, "score": 10} for i in range(5)]
    assert [r["id"] for r in filter_by_score(records, 10)] == [0, 1, 2, 3, 4]


def test_float_scores_supported():
    records = [{"id": 1, "score": 2.5}, {"id": 2, "score": 2.4}]
    assert [r["id"] for r in filter_by_score(records, 2.5)] == [1]
''',
        },
    },
    {
        "id": "return_missing_009",
        "title": "find_missing returns None instead of an empty list",
        "category": "return_value",
        "difficulty": "easy",
        "description": (
            "diffing.py implements find_missing(), which reports expected items absent from an "
            "actual collection. When nothing is missing it returns None because of a "
            "'result or None' shortcut, forcing callers to special-case the empty result. Fix "
            "it so the function always returns a list, preserving the order of ``expected`` and "
            "including duplicates that appear in ``expected``."
        ),
        "expected_behavior": (
            "find_missing([1, 2, 3], [1, 2, 3]) == []; find_missing(['a', 'b'], ['a']) == ['b']; "
            "duplicates in expected are reported individually."
        ),
        "files": {
            "diffing.py": '''"""Collection diffing helpers."""


def find_missing(expected, actual):
    """Return the items in ``expected`` that are absent from ``actual``."""
    result = []
    for item in expected:
        if item not in actual:
            result.append(item)
    return result or None
''',
            "tests/test_diffing.py": '''from diffing import find_missing


def test_reports_missing_item():
    assert find_missing(["a", "b"], ["a"]) == ["b"]


def test_reports_all_when_actual_empty():
    assert find_missing([1, 2], []) == [1, 2]


def test_nothing_missing_returns_empty_list():
    assert find_missing([1, 2, 3], [1, 2, 3]) == []
''',
        },
        "fixed": {
            "diffing.py": '''"""Collection diffing helpers."""


def find_missing(expected, actual):
    """Return the items in ``expected`` that are absent from ``actual``."""
    actual_set = set(actual)
    return [item for item in expected if item not in actual_set]
''',
        },
        "eval_tests": {
            "test_eval_diffing.py": '''from diffing import find_missing


def test_empty_result_is_a_list():
    result = find_missing([1, 2, 3], [1, 2, 3])
    assert result == []
    assert isinstance(result, list)


def test_preserves_expected_order():
    assert find_missing(["c", "a", "b"], ["b"]) == ["c", "a"]


def test_duplicates_in_expected_reported():
    assert find_missing(["a", "a", "b"], ["b"]) == ["a", "a"]


def test_both_empty():
    assert find_missing([], []) == []


def test_actual_superset():
    assert find_missing([1], [1, 2, 3]) == []


def test_works_with_generators():
    assert find_missing((x for x in [1, 2, 3]), [2]) == [1, 3]
''',
        },
    },
    {
        "id": "return_rounding_010",
        "title": "Currency rounding uses banker's rounding",
        "category": "return_value",
        "difficulty": "medium",
        "description": (
            "money.py rounds monetary amounts to two decimal places for invoices. It uses the "
            "built-in round(), which applies banker's rounding and binary floating point, so "
            "2.675 becomes 2.67 instead of the invoicing rule 2.68. Implement round_cents() "
            "using decimal arithmetic with ROUND_HALF_UP and return a float rounded to two "
            "decimal places."
        ),
        "expected_behavior": (
            "round_cents(2.675) == 2.68; round_cents(1.005) == 1.01; "
            "round_cents(-2.675) == -2.68; round_cents(10) == 10.0."
        ),
        "files": {
            "money.py": '''"""Monetary rounding helpers."""


def round_cents(amount):
    """Round ``amount`` to two decimal places using half-up rounding."""
    return round(amount, 2)
''',
            "tests/test_money.py": '''from money import round_cents


def test_rounds_down():
    assert round_cents(1.234) == 1.23


def test_rounds_up_plain():
    assert round_cents(1.239) == 1.24


def test_whole_number():
    assert round_cents(10) == 10.0


def test_half_up_at_third_decimal():
    assert round_cents(2.675) == 2.68
''',
        },
        "fixed": {
            "money.py": '''"""Monetary rounding helpers."""

from decimal import Decimal, ROUND_HALF_UP


def round_cents(amount):
    """Round ``amount`` to two decimal places using half-up rounding."""
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(value)
''',
        },
        "eval_tests": {
            "test_eval_money.py": '''from money import round_cents


def test_half_up_at_third_decimal():
    assert round_cents(2.675) == 2.68


def test_half_up_small_value():
    assert round_cents(1.005) == 1.01


def test_negative_half_up():
    assert round_cents(-2.675) == -2.68


def test_no_rounding_needed():
    assert round_cents(10) == 10.0
    assert round_cents(0.1) == 0.1


def test_rounds_down_below_half():
    assert round_cents(2.674) == 2.67


def test_zero_and_tiny():
    assert round_cents(0) == 0.0
    assert round_cents(0.004) == 0.0
''',
        },
    },
    {
        "id": "multifunc_memoize_011",
        "title": "Memoization cache ignores keyword arguments",
        "category": "multi_function",
        "difficulty": "hard",
        "description": (
            "caching.py provides a memoize decorator. Its cache key is built from positional "
            "arguments only, so calls that differ solely in keyword arguments return stale "
            "results. It also crashes when an argument is unhashable (for example a list). Fix "
            "memoize() so that keyword arguments participate in the key, calls with unhashable "
            "arguments are computed without caching, and cached calls still avoid re-invoking "
            "the wrapped function."
        ),
        "expected_behavior": (
            "Calls differing only by kwargs produce distinct results. A list argument works "
            "and is not cached. Repeated identical calls invoke the function once."
        ),
        "files": {
            "caching.py": '''"""Caching helpers."""

from functools import wraps


def memoize(func):
    """Cache results by positional arguments."""
    cache = {}

    @wraps(func)
    def wrapper(*args, **kwargs):
        key = args
        if key in cache:
            return cache[key]
        value = func(*args, **kwargs)
        cache[key] = value
        return value

    return wrapper
''',
            "tests/test_caching.py": '''from caching import memoize


def test_repeated_call_uses_cache():
    calls = []

    @memoize
    def double(x):
        calls.append(x)
        return x * 2

    assert double(2) == 4
    assert double(2) == 4
    assert calls == [2]


def test_different_positional_arguments():
    @memoize
    def add(a, b):
        return a + b

    assert add(1, 2) == 3
    assert add(2, 1) == 3


def test_kwargs_affect_cache_key():
    @memoize
    def scale(x, factor=1):
        return x * factor

    assert scale(2, factor=3) == 6
    assert scale(2, factor=4) == 8
''',
        },
        "fixed": {
            "caching.py": '''"""Caching helpers."""

from functools import wraps


def memoize(func):
    """Cache results by positional and keyword arguments."""
    cache = {}

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            key = (args, tuple(sorted(kwargs.items())))
            hash(key)
        except TypeError:
            return func(*args, **kwargs)
        if key in cache:
            return cache[key]
        value = func(*args, **kwargs)
        cache[key] = value
        return value

    return wrapper
''',
        },
        "eval_tests": {
            "test_eval_caching.py": '''from caching import memoize


def test_kwargs_affect_cache_key():
    calls = []

    @memoize
    def scale(x, factor=1):
        calls.append((x, factor))
        return x * factor

    assert scale(2, factor=3) == 6
    assert scale(2, factor=4) == 8
    assert len(calls) == 2


def test_repeated_kwargs_cached():
    calls = []

    @memoize
    def scale(x, factor=1):
        calls.append(1)
        return x * factor

    scale(2, factor=3)
    scale(2, factor=3)
    assert len(calls) == 1


def test_unhashable_argument_does_not_crash():
    @memoize
    def total(values):
        return sum(values)

    assert total([1, 2, 3]) == 6
    assert total([4, 5]) == 9


def test_mixed_arguments():
    @memoize
    def describe(a, b=2, c=3):
        return (a, b, c)

    assert describe(1, c=9) == (1, 2, 9)
    assert describe(1, c=9) == (1, 2, 9)


def test_metadata_preserved():
    @memoize
    def documented():
        """Doc."""

    assert documented.__name__ == "documented"
''',
        },
    },
    {
        "id": "multifunc_inventory_012",
        "title": "Inventory allows negative stock and invalid quantities",
        "category": "multi_function",
        "difficulty": "hard",
        "description": (
            "inventory.py implements an Inventory class used by the order service. remove() "
            "subtracts without checking available stock, so stock can go negative; add() accepts "
            "zero and negative quantities; and remove() on an unknown SKU creates a negative "
            "entry. Fix the class so add() requires a positive integer quantity, remove() raises "
            "ValueError when stock is insufficient or the SKU is unknown, and failed operations "
            "leave the inventory unchanged."
        ),
        "expected_behavior": (
            "Removing more than available raises ValueError and does not change stock. "
            "add(sku, 0) raises ValueError. available('unknown') == 0 and remove('unknown', 1) "
            "raises ValueError."
        ),
        "files": {
            "inventory.py": '''"""Simple in-memory inventory."""


class Inventory:
    """Tracks stock per SKU."""

    def __init__(self):
        self._stock = {}

    def add(self, sku, quantity):
        """Add ``quantity`` units of ``sku``."""
        self._stock[sku] = self._stock.get(sku, 0) + quantity
        return self._stock[sku]

    def remove(self, sku, quantity):
        """Remove ``quantity`` units of ``sku``."""
        self._stock[sku] = self._stock.get(sku, 0) - quantity
        return self._stock[sku]

    def available(self, sku):
        """Return current stock for ``sku``."""
        return self._stock.get(sku, 0)
''',
            "tests/test_inventory.py": '''import pytest

from inventory import Inventory


def test_add_and_read():
    inv = Inventory()
    assert inv.add("widget", 5) == 5
    assert inv.available("widget") == 5


def test_remove_reduces_stock():
    inv = Inventory()
    inv.add("widget", 5)
    assert inv.remove("widget", 2) == 3


def test_unknown_sku_is_zero():
    assert Inventory().available("nope") == 0


def test_over_removal_rejected():
    inv = Inventory()
    inv.add("widget", 3)
    with pytest.raises(ValueError):
        inv.remove("widget", 4)
    assert inv.available("widget") == 3
''',
        },
        "fixed": {
            "inventory.py": '''"""Simple in-memory inventory."""


class Inventory:
    """Tracks stock per SKU."""

    def __init__(self):
        self._stock = {}

    @staticmethod
    def _validate_quantity(quantity):
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise TypeError("quantity must be an int")
        if quantity <= 0:
            raise ValueError("quantity must be positive")

    def add(self, sku, quantity):
        """Add ``quantity`` units of ``sku``."""
        self._validate_quantity(quantity)
        self._stock[sku] = self._stock.get(sku, 0) + quantity
        return self._stock[sku]

    def remove(self, sku, quantity):
        """Remove ``quantity`` units of ``sku``."""
        self._validate_quantity(quantity)
        current = self._stock.get(sku, 0)
        if current < quantity:
            raise ValueError("insufficient stock for %s" % sku)
        self._stock[sku] = current - quantity
        return self._stock[sku]

    def available(self, sku):
        """Return current stock for ``sku``."""
        return self._stock.get(sku, 0)
''',
        },
        "eval_tests": {
            "test_eval_inventory.py": '''import pytest

from inventory import Inventory


def test_over_removal_rejected_and_state_unchanged():
    inv = Inventory()
    inv.add("widget", 3)
    with pytest.raises(ValueError):
        inv.remove("widget", 4)
    assert inv.available("widget") == 3


def test_zero_quantity_rejected():
    inv = Inventory()
    with pytest.raises(ValueError):
        inv.add("widget", 0)
    assert inv.available("widget") == 0


def test_negative_quantity_rejected():
    inv = Inventory()
    with pytest.raises(ValueError):
        inv.add("widget", -2)
    with pytest.raises(ValueError):
        inv.remove("widget", -1)


def test_unknown_sku_removal_rejected():
    inv = Inventory()
    with pytest.raises(ValueError):
        inv.remove("ghost", 1)
    assert inv.available("ghost") == 0


def test_exact_removal_allowed():
    inv = Inventory()
    inv.add("widget", 2)
    assert inv.remove("widget", 2) == 0
    assert inv.available("widget") == 0


def test_multiple_skus_independent():
    inv = Inventory()
    inv.add("a", 1)
    inv.add("b", 5)
    inv.remove("b", 4)
    assert inv.available("a") == 1
    assert inv.available("b") == 1
''',
        },
    },
    {
        "id": "multifile_settings_013",
        "title": "Settings loader mutates shared defaults across modules",
        "category": "multi_file",
        "difficulty": "hard",
        "description": (
            "The configuration package has two modules: defaults.py holds a module-level "
            "DEFAULTS dictionary including a nested 'headers' mapping, and settings.py merges "
            "caller overrides into it. load_settings() currently aliases DEFAULTS instead of "
            "copying it, so one call permanently changes the defaults seen by every later call, "
            "and nested dictionaries are shared. Fix settings.load_settings() so each call "
            "returns an independent deep copy and defaults.DEFAULTS is never modified. Do not "
            "change defaults.py."
        ),
        "expected_behavior": (
            "After load_settings({'timeout': 99}), defaults.DEFAULTS['timeout'] is still 30. "
            "Mutating the returned 'headers' does not affect DEFAULTS. Two calls are independent."
        ),
        "files": {
            "defaults.py": '''"""Shared default settings."""

DEFAULTS = {
    "retries": 2,
    "timeout": 30,
    "headers": {"accept": "application/json"},
}
''',
            "settings.py": '''"""Settings merging."""

from defaults import DEFAULTS


def load_settings(overrides=None):
    """Return defaults merged with ``overrides``."""
    merged = DEFAULTS
    if overrides:
        merged.update(overrides)
    return merged


def get_timeout(overrides=None):
    """Return the configured timeout in seconds."""
    return load_settings(overrides)["timeout"]
''',
            "tests/test_settings.py": '''from defaults import DEFAULTS
from settings import get_timeout, load_settings


def test_override_applied():
    assert load_settings({"timeout": 5})["timeout"] == 5


def test_defaults_present():
    settings = load_settings()
    assert settings["retries"] == 2
    assert settings["timeout"] == 30


def test_defaults_not_mutated_by_override():
    load_settings({"timeout": 99})
    assert DEFAULTS["timeout"] == 30


def test_get_timeout_reads_override():
    assert get_timeout({"timeout": 7}) == 7
''',
        },
        "fixed": {
            "settings.py": '''"""Settings merging."""

import copy

from defaults import DEFAULTS


def load_settings(overrides=None):
    """Return an independent copy of the defaults merged with ``overrides``."""
    merged = copy.deepcopy(DEFAULTS)
    if overrides:
        merged.update(overrides)
    return merged


def get_timeout(overrides=None):
    """Return the configured timeout in seconds."""
    return load_settings(overrides)["timeout"]
''',
        },
        "eval_tests": {
            "test_eval_settings.py": '''from defaults import DEFAULTS
from settings import get_timeout, load_settings


def test_defaults_not_mutated_by_override():
    load_settings({"timeout": 99})
    assert DEFAULTS["timeout"] == 30


def test_nested_headers_not_shared():
    settings = load_settings()
    settings["headers"]["accept"] = "text/plain"
    assert DEFAULTS["headers"]["accept"] == "application/json"


def test_two_calls_independent():
    first = load_settings({"timeout": 5})
    second = load_settings()
    assert first["timeout"] == 5
    assert second["timeout"] == 30


def test_override_does_not_leak_into_next_call():
    load_settings({"retries": 10, "extra": True})
    settings = load_settings()
    assert settings["retries"] == 2
    assert "extra" not in settings


def test_get_timeout_does_not_pollute_defaults():
    assert get_timeout({"timeout": 1}) == 1
    assert DEFAULTS["timeout"] == 30


def test_unknown_override_key_added_without_mutation():
    settings = load_settings({"region": "eu"})
    assert settings["region"] == "eu"
    assert "region" not in DEFAULTS
''',
        },
    },
    {
        "id": "multifile_pipeline_014",
        "title": "Cleaning pipeline drops rows before stripping whitespace",
        "category": "multi_file",
        "difficulty": "hard",
        "description": (
            "The data pipeline spans two modules. transforms.py provides strip_whitespace() and "
            "drop_empty(), while pipeline.py composes them in clean(). The stages are applied in "
            "the wrong order: drop_empty() runs before whitespace is stripped, so rows containing "
            "only spaces survive as 'non-empty', and the later strip leaves them blank. Fix "
            "pipeline.clean() so whitespace-only rows are removed, without changing either "
            "function in transforms.py."
        ),
        "expected_behavior": (
            "clean([{'name': '  '}, {'name': ' ok '}]) == [{'name': 'ok'}]. "
            "A row is empty when every value is blank after stripping."
        ),
        "files": {
            "transforms.py": '''"""Row-level transformations."""


def strip_whitespace(rows):
    """Return rows with every string value stripped."""
    return [
        {key: value.strip() if isinstance(value, str) else value for key, value in row.items()}
        for row in rows
    ]


def drop_empty(rows):
    """Return rows that contain at least one non-empty value."""
    return [row for row in rows if any(row.values())]
''',
            "pipeline.py": '''"""Composition of row transformations."""

from transforms import drop_empty, strip_whitespace


def clean(rows):
    """Strip whitespace and remove empty rows."""
    return strip_whitespace(drop_empty(rows))
''',
            "tests/test_pipeline.py": '''from pipeline import clean


def test_plain_rows_pass_through():
    rows = [{"name": "ada", "city": "london"}]
    assert clean(rows) == rows


def test_values_are_stripped():
    assert clean([{"name": "  ada  "}]) == [{"name": "ada"}]


def test_empty_list():
    assert clean([]) == []


def test_whitespace_only_row_removed():
    assert clean([{"name": "   "}, {"name": " ok "}]) == [{"name": "ok"}]
''',
        },
        "fixed": {
            "pipeline.py": '''"""Composition of row transformations."""

from transforms import drop_empty, strip_whitespace


def clean(rows):
    """Strip whitespace and remove empty rows."""
    return drop_empty(strip_whitespace(rows))
''',
        },
        "eval_tests": {
            "test_eval_pipeline.py": '''from pipeline import clean


def test_whitespace_only_row_removed():
    assert clean([{"name": "   "}, {"name": " ok "}]) == [{"name": "ok"}]


def test_all_blank_rows_removed():
    rows = [{"a": " ", "b": "  "}, {"a": "", "b": ""}]
    assert clean(rows) == []


def test_non_string_values_preserved():
    rows = [{"count": 0, "name": " x "}]
    assert clean(rows) == [{"count": 0, "name": "x"}]


def test_partial_blank_row_kept():
    assert clean([{"a": "", "b": "value"}]) == [{"a": "", "b": "value"}]


def test_order_preserved():
    rows = [{"n": " c "}, {"n": " "}, {"n": " a "}, {"n": " b "}]
    assert clean(rows) == [{"n": "c"}, {"n": "a"}, {"n": "b"}]


def test_input_rows_not_mutated():
    rows = [{"n": "  value  "}]
    clean(rows)
    assert rows == [{"n": "  value  "}]
''',
        },
    },
]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8", newline="\n")


def build_patch(task: dict[str, Any]) -> str:
    """Derive a unified diff from the buggy and fixed file contents."""
    chunks: list[str] = []
    for relative_path in sorted(task["fixed"]):
        before = task["files"][relative_path]
        after = task["fixed"][relative_path]
        if not before.endswith("\n"):
            before += "\n"
        if not after.endswith("\n"):
            after += "\n"
        diff = difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
            n=3,
        )
        chunks.append("".join(diff))
    return "".join(chunks)


def task_payload(task: dict[str, Any], patch: str) -> dict[str, Any]:
    return {
        "id": task["id"],
        "title": task["title"],
        "description": task["description"],
        "category": task["category"],
        "difficulty": task["difficulty"],
        "expected_behavior": task["expected_behavior"],
        "repo_dir": "repo",
        "feedback_test_paths": sorted(
            path for path in task["files"] if path.startswith("tests/")
        ),
        "feedback_command": ["python", "-m", "pytest", "tests", "-q"],
        "eval_command": ["python", "-m", "pytest", "eval_tests", "-q"],
        "reference_fix": "reference/fix.patch",
        "reference_fix_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
        "synthetic": True,
        "notes": (
            "Synthetic defect seeded for the VerifyLoop benchmark. Not a production incident."
        ),
    }


def write_task(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    task_dir = root / "tasks" / task["id"]
    if task_dir.exists():
        shutil.rmtree(task_dir)

    repo_dir = task_dir / "repo"
    for relative_path, content in task["files"].items():
        _write(repo_dir / relative_path, content)
    _write(repo_dir / "conftest.py", CONFTEST)
    _write(repo_dir / "README.md", f"# {task['title']}\n\n{task['description']}\n")

    for relative_path, content in task["eval_tests"].items():
        _write(task_dir / "eval_tests" / relative_path, content)

    patch = build_patch(task)
    _write(task_dir / "reference" / "fix.patch", patch)

    payload = task_payload(task, patch)
    _write(task_dir / "task.json", json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def build(check: bool = False) -> int:
    if check:
        return check_corpus()
    if BENCHMARK_DIR.exists():
        shutil.rmtree(BENCHMARK_DIR)
    BENCHMARK_DIR.mkdir(parents=True)

    entries = []
    for task in TASKS:
        payload = write_task(BENCHMARK_DIR, task)
        entries.append(
            {
                "id": payload["id"],
                "title": payload["title"],
                "category": payload["category"],
                "difficulty": payload["difficulty"],
                "path": f"tasks/{payload['id']}",
                "task_sha256": hashlib.sha256(
                    (BENCHMARK_DIR / "tasks" / payload["id"] / "task.json").read_bytes()
                ).hexdigest(),
            }
        )

    manifest = {
        "name": "verifyloop-synthetic",
        "version": BENCHMARK_VERSION,
        "description": (
            "Self-contained synthetic Python bug-fixing tasks with visible feedback tests and "
            "hidden evaluation tests. Every defect is deliberately seeded."
        ),
        "task_count": len(entries),
        "categories": sorted({entry["category"] for entry in entries}),
        "tasks": entries,
    }
    _write(BENCHMARK_DIR / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(entries)} tasks to {BENCHMARK_DIR}")
    return 0


def check_corpus() -> int:
    """Verify generated artifacts match what the generator would produce."""
    problems: list[str] = []
    manifest_path = BENCHMARK_DIR / "manifest.json"
    if not manifest_path.is_file():
        print("manifest missing; run without --check", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["task_count"] != len(TASKS):
        problems.append(
            f"manifest lists {manifest['task_count']} tasks, generator has {len(TASKS)}"
        )
    for task in TASKS:
        task_dir = BENCHMARK_DIR / "tasks" / task["id"]
        if not task_dir.is_dir():
            problems.append(f"{task['id']}: missing directory")
            continue
        patch = build_patch(task)
        on_disk = (task_dir / "reference" / "fix.patch").read_text(encoding="utf-8")
        if patch != on_disk:
            problems.append(f"{task['id']}: reference patch is stale")
        for relative_path, content in task["files"].items():
            disk = (task_dir / "repo" / relative_path).read_text(encoding="utf-8")
            if disk != content:
                problems.append(f"{task['id']}: {relative_path} differs from generator")
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print("benchmark corpus is in sync")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify instead of writing")
    args = parser.parse_args()
    raise SystemExit(build(check=args.check))
