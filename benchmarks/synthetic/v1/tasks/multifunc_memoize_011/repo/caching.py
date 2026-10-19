"""Caching helpers."""

from functools import wraps


def memoize(func):
    """Cache results by positional arguments."""
    cache = {}

    @wraps(func)
    def wrapper(*args, **kwargs):
        key = args
        if key in cache:
            return cache[key]
        value = func(*args, **kwargs)
        cache[key] = value
        return value

    return wrapper
