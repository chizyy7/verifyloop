# CSV line parser breaks on quoted commas

ingest.py parses a single CSV line with str.split(','). Fields that contain a comma inside double quotes are therefore split incorrectly, and quoted fields keep their surrounding quotes. Replace the manual split with Python's csv module so quoted commas and doubled quotes are handled correctly, while plain lines keep working.
