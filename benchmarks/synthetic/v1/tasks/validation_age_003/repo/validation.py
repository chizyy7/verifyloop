"""Input validation for the user profile service."""


def validate_age(value):
    """Return a validated age, or raise on invalid input."""
    if not isinstance(value, int):
        raise TypeError("age must be an int")
    if value > 150:
        raise ValueError("age must be between 0 and 150")
    return value
