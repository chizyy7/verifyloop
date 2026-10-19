import pytest

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
