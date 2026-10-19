"""Small descriptive statistics helpers."""


def mean(values):
    """Arithmetic mean of a non-empty sequence."""
    return sum(values) / len(values)


def median(values):
    """Median of a non-empty sequence."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle]
