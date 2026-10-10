"""``${...}`` interpolation for INI values."""

from __future__ import annotations

from typing import Callable


class InterpolationError(ValueError):
    """A value could not be interpolated."""


def interpolate(
    value: str,
    section: str,
    lookup: Callable[[str, str], str | None],
    _stack: tuple[tuple[str, str], ...] = (),
) -> str:
    """Interpolate ``value`` living in ``section``.

    ``lookup(section, key)`` returns the raw text or ``None`` when missing.
    ``_stack`` holds the (section, key) pairs being resolved, for cycle detection.
    """
    out: list[str] = []
    i, n = 0, len(value)
    while i < n:
        ch = value[i]
        if ch != "$":
            out.append(ch)
            i += 1
            continue
        nxt = value[i + 1] if i + 1 < n else ""
        if nxt == "$":
            out.append("$")
            i += 2
        elif nxt == "{":
            end = value.find("}", i + 2)
            if end < 0:
                raise InterpolationError(f"unterminated '${{' in {value!r}")
            body = value[i + 2 : end]
            name, sep, default = body.partition("|")
            name = name.strip()
            if not name:
                raise InterpolationError("empty reference name")
            ref_section, colon, ref_key = name.partition(":")
            if not colon:
                ref_section, ref_key = section, name
            target = (ref_section, ref_key)
            if target in _stack:
                chain = " -> ".join(f"{s}:{k}" for s, k in (*_stack, target))
                raise InterpolationError(f"reference cycle: {chain}")
            raw = lookup(ref_section, ref_key)
            if raw is None:
                if sep:
                    out.append(default)
                else:
                    raise InterpolationError(f"missing reference: {name}")
            else:
                out.append(interpolate(raw, ref_section, lookup, _stack + (target,)))
            i = end + 1
        else:
            out.append("$")
            i += 1
    return "".join(out)
