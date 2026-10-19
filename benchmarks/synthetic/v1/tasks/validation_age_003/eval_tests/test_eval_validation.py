import pytest

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
