from defaults import DEFAULTS
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
