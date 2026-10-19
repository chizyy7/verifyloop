"""Search helpers used by the index builder."""


def binary_search(items, target):
    """Return the index of ``target`` in the sorted sequence ``items``.

    Returns -1 when the target is absent. When duplicates exist, the index of the
    first occurrence is required.
    """
    low, high = 0, len(items) - 1
    while low <= high:
        middle = (low + high) // 2
        if items[middle] == target:
            return middle
        if items[middle] < target:
            low = middle + 1
        else:
            high = middle - 1
    return -1
