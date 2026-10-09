"""Command-line interface: ``python -m levelcount FILE [FILE ...]``."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from typing import Sequence

from .parse import ALIASES, LEVELS, count_levels


def parse_level(value: str) -> str:
    """argparse type: a canonical level name from a case-insensitive name or alias."""
    word = value.strip().upper()
    word = ALIASES.get(word, word)
    if word not in LEVELS:
        raise argparse.ArgumentTypeError(
            f"invalid level {value!r} (choose from {', '.join(LEVELS)})"
        )
    return word


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="levelcount", description="Count log lines per severity level."
    )
    parser.add_argument("files", nargs="+", help="log files to read ('-' for stdin)")
    parser.add_argument("--json", action="store_true", help="print a JSON object instead of a table")
    parser.add_argument(
        "-m",
        "--min-level",
        type=parse_level,
        default=LEVELS[0],
        metavar="LEVEL",
        help=f"only count levels at or above LEVEL ({', '.join(LEVELS)}; case-insensitive)",
    )
    return parser


def _read(path: str) -> list[str]:
    if path == "-":
        return sys.stdin.read().splitlines()
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read().splitlines()


def render(counts: Counter[str], as_json: bool, min_level: str = LEVELS[0]) -> str:
    shown = LEVELS[LEVELS.index(min_level):]
    present = [(level, counts[level]) for level in shown if counts[level]]
    if as_json:
        return json.dumps(dict(present))
    lines = [f"{level:<8} {n}" for level, n in present]
    lines.append(f"{'TOTAL':<8} {sum(n for _, n in present)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    counts: Counter[str] = Counter()
    for path in args.files:
        try:
            counts.update(count_levels(_read(path)))
        except OSError as exc:
            print(f"levelcount: cannot read {path}: {exc.strerror}", file=sys.stderr)
            return 1
    print(render(counts, args.json, args.min_level))
    return 0
