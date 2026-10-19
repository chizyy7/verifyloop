import pytest

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
