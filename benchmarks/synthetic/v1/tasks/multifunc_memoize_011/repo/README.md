# Memoization cache ignores keyword arguments

caching.py provides a memoize decorator. Its cache key is built from positional arguments only, so calls that differ solely in keyword arguments return stale results. It also crashes when an argument is unhashable (for example a list). Fix memoize() so that keyword arguments participate in the key, calls with unhashable arguments are computed without caching, and cached calls still avoid re-invoking the wrapped function.
