"""Composition of row transformations."""

from transforms import drop_empty, strip_whitespace


def clean(rows):
    """Strip whitespace and remove empty rows."""
    return strip_whitespace(drop_empty(rows))
