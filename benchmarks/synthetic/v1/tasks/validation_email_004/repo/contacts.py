"""Contact string parsing."""

import re

EMAIL_RE = re.compile(r"^[a-z]+@[a-z]+\.[a-z]+$")


def parse_contact(text):
    """Parse ``"Name <email>"`` into ``(name, email)``."""
    if "<" not in text or not text.endswith(">"):
        raise ValueError("expected format: Name <email>")
    name, _, rest = text.partition("<")
    email = rest[:-1].strip()
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")
    if not EMAIL_RE.match(email):
        raise ValueError("invalid email address: %s" % email)
    return name, email
