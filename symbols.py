"""Symbol file parsing and normalization."""

from __future__ import annotations

from pathlib import Path


def load_tickers(path: Path) -> list[str]:
    """Read ticker symbols from a text file, one per line."""
    if not path.exists():
        raise FileNotFoundError(f"Tickers file not found: {path}")

    tickers: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tickers.append(stripped.upper())

    if not tickers:
        raise ValueError(f"No tickers found in {path}")

    return tickers


def parse_symbols_arg(value: str) -> list[str]:
    """Parse a comma-separated symbol list; uppercases and drops blanks."""
    symbols = [part.strip().upper() for part in value.split(",")]
    return [symbol for symbol in symbols if symbol]
