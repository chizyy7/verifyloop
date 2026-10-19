# find_missing returns None instead of an empty list

diffing.py implements find_missing(), which reports expected items absent from an actual collection. When nothing is missing it returns None because of a 'result or None' shortcut, forcing callers to special-case the empty result. Fix it so the function always returns a list, preserving the order of ``expected`` and including duplicates that appear in ``expected``.
