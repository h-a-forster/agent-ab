"""Plain-text tables."""

from __future__ import annotations

from .width import display_width
from .wrap import wrap


def _pad(line: str, width: int, align: str) -> str:
    gap = max(0, width - len(line))
    if align == "r":
        return " " * gap + line
    if align == "c":
        return " " * (gap // 2) + line + " " * (gap - gap // 2)
    return line + " " * gap


def render_table(rows: list[list[str]], widths: list[int], aligns: str = "") -> str:
    """Render ``rows`` as text, wrapping each cell to its column width."""
    out: list[str] = []
    for row in rows:
        if len(row) > len(widths):
            raise ValueError("row has more cells than columns")
        cells = [wrap(cell, w) for cell, w in zip(row, widths)]
        cells += [[""] for _ in widths[len(row) :]]
        height = max(len(c) for c in cells)
        for i in range(height):
            parts = []
            for col, lines in enumerate(cells):
                align = aligns[col] if col < len(aligns) else "l"
                parts.append(_pad(lines[i] if i < len(lines) else "", widths[col], align))
            out.append(" | ".join(parts).rstrip(" "))
    return "\n".join(out)
