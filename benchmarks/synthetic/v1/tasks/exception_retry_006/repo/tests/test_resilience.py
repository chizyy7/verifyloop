import pytest

from resilience import retry


def test_success_passes_through():
    @retry(times=3)
    def ok():
        return "value"

    assert ok() == "value"


def test_invalid_times_rejected():
    with pytest.raises(ValueError):
        retry(times=0)


def test_single_attempt_is_made():
    calls = []

    @retry(times=1)
    def flaky():
        calls.append(1)
        raise RuntimeError("always")

    with pytest.raises(RuntimeError):
        flaky()
    assert len(calls) == 1


def test_non_matching_exception_propagates():
    @retry(times=3, exceptions=(ValueError,))
    def boom():
        raise KeyError("nope")

    with pytest.raises(KeyError):
        boom()
