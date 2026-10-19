import pytest

from contacts import parse_contact


def test_plus_tag_accepted():
    assert parse_contact("Ada <ada+research@example.com>") == (
        "Ada",
        "ada+research@example.com",
    )


def test_digits_and_dots_accepted():
    name, email = parse_contact("Grace <grace.m.hopper2@navy.mil>")
    assert name == "Grace"
    assert email == "grace.m.hopper2@navy.mil"


def test_multi_level_domain_accepted():
    assert parse_contact("Alan <alan@math.example.co.uk>")[1] == "alan@math.example.co.uk"


def test_hyphenated_domain_accepted():
    assert parse_contact("Linus <linus@kernel-archive.org>")[1] == "linus@kernel-archive.org"


def test_domain_without_dot_rejected():
    with pytest.raises(ValueError):
        parse_contact("Ada <ada@localhost>")


def test_empty_name_rejected():
    with pytest.raises(ValueError):
        parse_contact(" <ada@example.com>")
