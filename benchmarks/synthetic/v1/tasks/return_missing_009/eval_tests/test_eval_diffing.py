from diffing import find_missing


def test_empty_result_is_a_list():
    result = find_missing([1, 2, 3], [1, 2, 3])
    assert result == []
    assert isinstance(result, list)


def test_preserves_expected_order():
    assert find_missing(["c", "a", "b"], ["b"]) == ["c", "a"]


def test_duplicates_in_expected_reported():
    assert find_missing(["a", "a", "b"], ["b"]) == ["a", "a"]


def test_both_empty():
    assert find_missing([], []) == []


def test_actual_superset():
    assert find_missing([1], [1, 2, 3]) == []


def test_works_with_generators():
    assert find_missing((x for x in [1, 2, 3]), [2]) == [1, 3]
