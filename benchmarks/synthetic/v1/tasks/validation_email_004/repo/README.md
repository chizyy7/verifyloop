# Contact parser rejects valid email addresses

contacts.py parses 'Name <email>' strings. The current email check only allows lowercase letters and a single dot, so addresses containing digits, dots in the local part, or a plus tag are wrongly rejected. Fix parse_contact() so it accepts common valid addresses (letters, digits, dots, underscores, plus tags, hyphens in the domain), still rejects strings without an @ or with no dot in the domain, and keeps raising ValueError for malformed input.
