"""Allow ``python -m verifyloop`` to behave like the console script."""

from verifyloop.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
