# Pagination drops the last item of every page

The paginate() helper in paging.py is used by the reporting service to slice records into pages. Users report that every page is missing its final record: page 1 of 10 items with per_page=3 returns only 2 items. Fix paginate() so that a full page contains per_page items, a partial final page returns the remainder, and out-of-range pages return an empty list. Keep the existing validation that page and per_page must be >= 1.
