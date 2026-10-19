"""Settings merging."""

from defaults import DEFAULTS


def load_settings(overrides=None):
    """Return defaults merged with ``overrides``."""
    merged = DEFAULTS
    if overrides:
        merged.update(overrides)
    return merged


def get_timeout(overrides=None):
    """Return the configured timeout in seconds."""
    return load_settings(overrides)["timeout"]
