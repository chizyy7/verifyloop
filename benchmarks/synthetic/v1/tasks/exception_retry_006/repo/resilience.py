"""Retry helpers."""

from functools import wraps


def retry(times, exceptions=(Exception,)):
    """Retry ``times`` total attempts when one of ``exceptions`` is raised."""
    if times < 1:
        raise ValueError("times must be >= 1")

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for _ in range(times - 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_error = exc
            raise last_error

        return wrapper

    return decorator
