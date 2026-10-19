from pipeline import clean


def test_whitespace_only_row_removed():
    assert clean([{"name": "   "}, {"name": " ok "}]) == [{"name": "ok"}]


def test_all_blank_rows_removed():
    rows = [{"a": " ", "b": "  "}, {"a": "", "b": ""}]
    assert clean(rows) == []


def test_non_string_values_preserved():
    rows = [{"count": 0, "name": " x "}]
    assert clean(rows) == [{"count": 0, "name": "x"}]


def test_partial_blank_row_kept():
    assert clean([{"a": "", "b": "value"}]) == [{"a": "", "b": "value"}]


def test_order_preserved():
    rows = [{"n": " c "}, {"n": " "}, {"n": " a "}, {"n": " b "}]
    assert clean(rows) == [{"n": "c"}, {"n": "a"}, {"n": "b"}]


def test_input_rows_not_mutated():
    rows = [{"n": "  value  "}]
    clean(rows)
    assert rows == [{"n": "  value  "}]
