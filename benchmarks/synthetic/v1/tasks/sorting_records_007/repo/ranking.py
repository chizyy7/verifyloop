"""Leaderboard ordering."""


def sort_records(records, key="score", descending=True):
    """Return records ordered by ``key`` with name as the tie-breaker."""
    return sorted(records, key=lambda record: (record[key], record["name"]), reverse=descending)
