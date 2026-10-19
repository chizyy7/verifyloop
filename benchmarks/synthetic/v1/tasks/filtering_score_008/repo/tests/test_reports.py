from reports import filter_by_score


def test_above_threshold_kept():
    records = [{"id": 1, "score": 8}, {"id": 2, "score": 3}]
    assert [r["id"] for r in filter_by_score(records, 5)] == [1]


def test_threshold_is_inclusive():
    records = [{"id": 1, "score": 5}, {"id": 2, "score": 4}]
    assert [r["id"] for r in filter_by_score(records, 5)] == [1]


def test_empty_input():
    assert filter_by_score([], 5) == []
