from ranking import sort_records


def test_highest_score_first():
    records = [
        {"name": "a", "score": 1},
        {"name": "b", "score": 9},
        {"name": "c", "score": 5},
    ]
    assert [r["name"] for r in sort_records(records)] == ["b", "c", "a"]


def test_ascending_mode():
    records = [{"name": "a", "score": 2}, {"name": "b", "score": 1}]
    assert [r["name"] for r in sort_records(records, descending=False)] == ["b", "a"]


def test_ties_break_by_name_ascending():
    records = [
        {"name": "zeta", "score": 10},
        {"name": "alpha", "score": 10},
    ]
    assert [r["name"] for r in sort_records(records)] == ["alpha", "zeta"]
