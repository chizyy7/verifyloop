"""Row-level transformations."""


def strip_whitespace(rows):
    """Return rows with every string value stripped."""
    return [
        {key: value.strip() if isinstance(value, str) else value for key, value in row.items()}
        for row in rows
    ]


def drop_empty(rows):
    """Return rows that contain at least one non-empty value."""
    return [row for row in rows if any(row.values())]
