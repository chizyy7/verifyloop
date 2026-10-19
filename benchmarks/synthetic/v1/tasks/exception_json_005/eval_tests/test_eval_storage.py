import json

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
