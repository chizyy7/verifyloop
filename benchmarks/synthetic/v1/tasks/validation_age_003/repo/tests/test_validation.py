import pytest

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
