import pytest

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
