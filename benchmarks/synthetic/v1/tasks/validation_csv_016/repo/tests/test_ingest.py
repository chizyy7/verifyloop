from ingest import parse_csv_line


def test_plain_line():
    assert parse_csv_line("a,b,c") == ["a", "b", "c"]


def test_single_field():
    assert parse_csv_line("only") == ["only"]


def test_empty_line():
    assert parse_csv_line("") == []


def test_quoted_comma():
    assert parse_csv_line('a,"b,c",d') == ["a", "b,c", "d"]
