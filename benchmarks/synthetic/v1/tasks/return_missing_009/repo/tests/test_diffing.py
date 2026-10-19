from diffing import find_missing


def test_reports_missing_item():
    assert find_missing(["a", "b"], ["a"]) == ["b"]


def test_reports_all_when_actual_empty():
    assert find_missing([1, 2], []) == [1, 2]


def test_nothing_missing_returns_empty_list():
    assert find_missing([1, 2, 3], [1, 2, 3]) == []
