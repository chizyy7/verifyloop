import pytest

from resilience import retry


def test_single_attempt_still_calls_once():
    calls = []

    @retry(times=1)
    def flaky():
        calls.append(1)
        raise RuntimeError("always")

    with pytest.raises(RuntimeError):
        flaky()
    assert len(calls) == 1


def test_recovers_on_third_attempt():
    calls = []

    @retry(times=3)
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("not yet")
        return "done"

    assert flaky() == "done"
    assert len(calls) == 3


def test_exhausts_exactly_times_attempts():
    calls = []

    @retry(times=4)
    def always_fails():
        calls.append(1)
        raise ValueError("nope")

    with pytest.raises(ValueError):
        always_fails()
    assert len(calls) == 4


def test_preserves_metadata():
    @retry(times=2)
    def documented():
        """Docstring."""

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Docstring."


def test_arguments_forwarded():
    @retry(times=2)
    def add(a, b=0):
        return a + b

    assert add(2, b=5) == 7
