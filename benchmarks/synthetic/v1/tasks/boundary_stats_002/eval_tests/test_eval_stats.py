import pytest

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
