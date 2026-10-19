"""Report filtering helpers."""


def filter_by_score(records, minimum):
    """Return records whose score is at least ``minimum``."""
    return [record for record in records if record["score"] > minimum]
