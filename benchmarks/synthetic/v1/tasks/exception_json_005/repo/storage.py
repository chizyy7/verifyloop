"""JSON file helpers."""

import json


def load_json(path, default=None):
    """Load JSON from ``path``, returning ``default`` when it cannot be read."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default
