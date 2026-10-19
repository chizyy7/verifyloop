# Binary search returns an arbitrary duplicate index

search.py implements binary_search over a sorted list. The function currently returns whichever matching index the midpoint lands on, but its documented contract requires the index of the *first* occurrence of the target. Fix the implementation so it returns the first index, keeps returning -1 for missing values, and remains O(log n).
