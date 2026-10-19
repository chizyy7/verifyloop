from money import round_cents


def test_half_up_at_third_decimal():
    assert round_cents(2.675) == 2.68


def test_half_up_small_value():
    assert round_cents(1.005) == 1.01


def test_negative_half_up():
    assert round_cents(-2.675) == -2.68


def test_no_rounding_needed():
    assert round_cents(10) == 10.0
    assert round_cents(0.1) == 0.1


def test_rounds_down_below_half():
    assert round_cents(2.674) == 2.67


def test_zero_and_tiny():
    assert round_cents(0) == 0.0
    assert round_cents(0.004) == 0.0
