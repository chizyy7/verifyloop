import json

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
