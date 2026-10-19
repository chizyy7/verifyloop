# Descending sort also reverses the tie-breaker

ranking.py sorts score records for a leaderboard. The intended order is score descending, and ties must be broken by name ascending. The current implementation puts both fields in one tuple key and reverses the whole tuple, so tied names come out descending as well. Fix the ordering while keeping the function pure and stable.
