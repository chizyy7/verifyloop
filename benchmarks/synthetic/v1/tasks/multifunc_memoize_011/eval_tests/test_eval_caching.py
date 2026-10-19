from caching import memoize


def test_kwargs_affect_cache_key():
    calls = []

    @memoize
    def scale(x, factor=1):
        calls.append((x, factor))
        return x * factor

    assert scale(2, factor=3) == 6
    assert scale(2, factor=4) == 8
    assert len(calls) == 2


def test_repeated_kwargs_cached():
    calls = []

    @memoize
    def scale(x, factor=1):
        calls.append(1)
        return x * factor

    scale(2, factor=3)
    scale(2, factor=3)
    assert len(calls) == 1


def test_unhashable_argument_does_not_crash():
    @memoize
    def total(values):
        return sum(values)

    assert total([1, 2, 3]) == 6
    assert total([4, 5]) == 9


def test_mixed_arguments():
    @memoize
    def describe(a, b=2, c=3):
        return (a, b, c)

    assert describe(1, c=9) == (1, 2, 9)
    assert describe(1, c=9) == (1, 2, 9)


def test_metadata_preserved():
    @memoize
    def documented():
        """Doc."""

    assert documented.__name__ == "documented"
