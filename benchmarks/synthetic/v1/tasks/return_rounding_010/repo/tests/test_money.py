from money import round_cents


def test_rounds_down():
    assert round_cents(1.234) == 1.23


def test_rounds_up_plain():
    assert round_cents(1.239) == 1.24


def test_whole_number():
    assert round_cents(10) == 10.0


def test_half_up_at_third_decimal():
    assert round_cents(2.675) == 2.68
