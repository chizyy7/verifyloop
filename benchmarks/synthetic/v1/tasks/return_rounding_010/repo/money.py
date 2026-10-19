"""Monetary rounding helpers."""


def round_cents(amount):
    """Round ``amount`` to two decimal places using half-up rounding."""
    return round(amount, 2)
