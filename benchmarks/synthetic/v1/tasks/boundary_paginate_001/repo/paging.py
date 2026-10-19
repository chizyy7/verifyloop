"""Pagination helpers for the reporting service."""


def paginate(items, page, per_page):
    """Return one page of ``items``.

    ``page`` is 1-based. A page holds at most ``per_page`` items.
    """
    if page < 1:
        raise ValueError("page must be >= 1")
    if per_page < 1:
        raise ValueError("per_page must be >= 1")
    start = (page - 1) * per_page
    end = start + per_page - 1
    return list(items[start:end])
