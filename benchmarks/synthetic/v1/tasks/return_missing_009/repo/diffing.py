"""Collection diffing helpers."""


def find_missing(expected, actual):
    """Return the items in ``expected`` that are absent from ``actual``."""
    result = []
    for item in expected:
        if item not in actual:
            result.append(item)
    return result or None
