"""Allow ``python -m benchmarks`` as a shorthand for the benchmark CLI."""

from benchmarks.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
