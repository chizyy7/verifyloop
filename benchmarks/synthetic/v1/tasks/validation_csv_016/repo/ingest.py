"""Line-oriented CSV ingestion."""


def parse_csv_line(line):
    """Split one CSV line into fields."""
    return line.split(",")
