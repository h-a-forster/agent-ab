"""ANSI SGR escape handling."""

from __future__ import annotations

import re

SGR = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Remove SGR escape sequences."""
    return SGR.sub("", text)


def tokens(text: str) -> list[tuple[bool, str]]:
    """Split ``text`` into ``(is_ansi, piece)`` tokens: one per SGR sequence or character."""
    out: list[tuple[bool, str]] = []
    pos = 0
    for match in SGR.finditer(text):
        out.extend((False, ch) for ch in text[pos : match.start()])
        out.append((True, match.group()))
        pos = match.end()
    out.extend((False, ch) for ch in text[pos:])
    return out


def update_open(open_seqs: list[str], piece: str) -> None:
    """Apply one SGR sequence to the list of currently open sequences."""
    params = piece[2:-1]
    if params in ("", "0"):
        open_seqs.clear()
    else:
        open_seqs.append(piece)


def close_styles(lines: list[str]) -> list[str]:
    """Make every non-empty line self-contained, carrying open styles to the next line."""
    open_seqs: list[str] = []
    out: list[str] = []
    for line in lines:
        prefix = "".join(open_seqs)
        for is_ansi, piece in tokens(line):
            if is_ansi:
                update_open(open_seqs, piece)
        if line == "":
            out.append(line)
            continue
        out.append(prefix + line + ("\x1b[0m" if open_seqs else ""))
    return out
