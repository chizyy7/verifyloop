# Statistics helpers fail on empty and even-length input

The analytics module (stats.py) exposes mean() and median(). Two defects are reported. First, both functions raise an implementation-level error on an empty sequence instead of a ValueError with a clear message. Second, median() returns the upper middle element for even-length sequences instead of the average of the two middle elements. Fix both while keeping the functions pure.
