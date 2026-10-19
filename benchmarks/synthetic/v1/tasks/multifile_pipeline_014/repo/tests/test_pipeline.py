from pipeline import clean


def test_plain_rows_pass_through():
    rows = [{"name": "ada", "city": "london"}]
    assert clean(rows) == rows


def test_values_are_stripped():
    assert clean([{"name": "  ada  "}]) == [{"name": "ada"}]


def test_empty_list():
    assert clean([]) == []


def test_whitespace_only_row_removed():
    assert clean([{"name": "   "}, {"name": " ok "}]) == [{"name": "ok"}]
