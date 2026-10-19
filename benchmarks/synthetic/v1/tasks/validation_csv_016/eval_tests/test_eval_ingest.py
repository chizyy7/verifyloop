from ingest import parse_csv_line


def test_quoted_comma():
    assert parse_csv_line('a,"b,c",d') == ["a", "b,c", "d"]


def test_escaped_quotes():
    assert parse_csv_line('a,"say ""hi""",b') == ["a", 'say "hi"', "b"]


def test_empty_fields_preserved():
    assert parse_csv_line("a,,c") == ["a", "", "c"]


def test_trailing_comma():
    assert parse_csv_line("a,b,") == ["a", "b", ""]


def test_quoted_newline_free_text():
    assert parse_csv_line('"one,two",three') == ["one,two", "three"]
