from search import binary_search


def test_returns_first_duplicate():
    assert binary_search([1, 2, 2, 2, 3], 2) == 1
    assert binary_search([0, 0, 0], 0) == 0
    assert binary_search([1, 1, 2, 2], 2) == 2


def test_last_duplicate_region():
    assert binary_search([1, 2, 3, 3, 3], 3) == 2


def test_single_element():
    assert binary_search([42], 42) == 0
    assert binary_search([42], 7) == -1


def test_large_sequence_is_logarithmic():
    items = list(range(10000))
    assert binary_search(items, 9999) == 9999
    assert binary_search(items, 5000) == 5000
    assert binary_search(items, -1) == -1
