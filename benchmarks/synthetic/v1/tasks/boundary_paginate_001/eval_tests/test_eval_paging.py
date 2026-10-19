import pytest

from paging import paginate


def test_last_partial_page():
    assert paginate(list(range(10)), 4, 3) == [9]


def test_out_of_range_page_is_empty():
    assert paginate(list(range(10)), 9, 3) == []


def test_per_page_one():
    assert paginate(["a", "b", "c"], 2, 1) == ["b"]


def test_no_items_lost_across_pages():
    items = list(range(17))
    collected = []
    for page in range(1, 8):
        collected.extend(paginate(items, page, 3))
    assert collected == items


def test_accepts_iterators():
    assert paginate(iter(range(5)), 1, 2) == [0, 1]


def test_validation_errors_preserved():
    with pytest.raises(ValueError):
        paginate([], 0, 1)
    with pytest.raises(ValueError):
        paginate([], 1, -1)
