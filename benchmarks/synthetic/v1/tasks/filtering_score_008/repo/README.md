# Score filter excludes the boundary and crashes on missing data

reports.py filters records by a minimum score. Two defects are reported: the comparison uses > so records exactly at the threshold are dropped, and records without a usable numeric score raise KeyError or TypeError instead of being skipped. Fix filter_by_score() so the threshold is inclusive and records with a missing or non-numeric score are excluded without raising.
