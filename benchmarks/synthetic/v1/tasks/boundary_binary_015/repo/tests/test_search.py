from search import binary_search


def test_finds_present_value():
    assert binary_search([1, 3, 5, 7], 5) == 2


def test_missing_value():
    assert binary_search([1, 3, 5, 7], 4) == -1


def test_empty_sequence():
    assert binary_search([], 1) == -1


def test_returns_first_duplicate():
    assert binary_search([1, 2, 2, 2, 3], 2) == 1
