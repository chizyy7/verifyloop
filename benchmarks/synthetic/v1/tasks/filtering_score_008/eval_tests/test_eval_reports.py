from reports import filter_by_score


def test_threshold_is_inclusive():
    records = [{"id": 1, "score": 5}, {"id": 2, "score": 4}]
    assert [r["id"] for r in filter_by_score(records, 5)] == [1]


def test_missing_score_skipped():
    records = [{"id": 1}, {"id": 2, "score": 9}]
    assert [r["id"] for r in filter_by_score(records, 0)] == [2]


def test_none_score_skipped():
    records = [{"id": 1, "score": None}, {"id": 2, "score": 3}]
    assert [r["id"] for r in filter_by_score(records, 0)] == [2]


def test_string_score_skipped():
    records = [{"id": 1, "score": "9"}, {"id": 2, "score": 3}]
    assert [r["id"] for r in filter_by_score(records, 0)] == [2]


def test_order_preserved():
    records = [{"id": i, "score": 10} for i in range(5)]
    assert [r["id"] for r in filter_by_score(records, 10)] == [0, 1, 2, 3, 4]


def test_float_scores_supported():
    records = [{"id": 1, "score": 2.5}, {"id": 2, "score": 2.4}]
    assert [r["id"] for r in filter_by_score(records, 2.5)] == [1]
