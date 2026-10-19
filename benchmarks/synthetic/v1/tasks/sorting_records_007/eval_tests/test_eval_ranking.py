from ranking import sort_records


def test_ties_break_by_name_ascending():
    records = [
        {"name": "zeta", "score": 10},
        {"name": "alpha", "score": 10},
        {"name": "mike", "score": 10},
    ]
    assert [r["name"] for r in sort_records(records)] == ["alpha", "mike", "zeta"]


def test_ties_ascending_mode_still_name_ascending():
    records = [
        {"name": "beta", "score": 1},
        {"name": "alpha", "score": 1},
    ]
    assert [r["name"] for r in sort_records(records, descending=False)] == ["alpha", "beta"]


def test_input_not_mutated():
    records = [{"name": "b", "score": 1}, {"name": "a", "score": 2}]
    original = [dict(r) for r in records]
    sort_records(records)
    assert records == original


def test_custom_key():
    records = [{"name": "a", "wins": 2}, {"name": "b", "wins": 7}]
    assert [r["name"] for r in sort_records(records, key="wins")] == ["b", "a"]


def test_empty_and_single():
    assert sort_records([]) == []
    assert sort_records([{"name": "only", "score": 1}]) == [{"name": "only", "score": 1}]
