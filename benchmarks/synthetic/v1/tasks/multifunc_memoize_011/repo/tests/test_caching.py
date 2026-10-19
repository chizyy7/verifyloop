from caching import memoize


def test_repeated_call_uses_cache():
    calls = []

    @memoize
    def double(x):
        calls.append(x)
        return x * 2

    assert double(2) == 4
    assert double(2) == 4
    assert calls == [2]


def test_different_positional_arguments():
    @memoize
    def add(a, b):
        return a + b

    assert add(1, 2) == 3
    assert add(2, 1) == 3


def test_kwargs_affect_cache_key():
    @memoize
    def scale(x, factor=1):
        return x * factor

    assert scale(2, factor=3) == 6
    assert scale(2, factor=4) == 8
