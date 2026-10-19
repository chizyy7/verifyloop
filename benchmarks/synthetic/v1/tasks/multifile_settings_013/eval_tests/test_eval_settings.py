from defaults import DEFAULTS
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
