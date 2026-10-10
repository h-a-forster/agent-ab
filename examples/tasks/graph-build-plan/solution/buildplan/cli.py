"""Command line interface."""

import sys

from .graph import GraphError
from .order import affected, levels, topo_order
from .spec import SpecError, parse_spec


class _Usage(Exception):
    pass


def _parse_args(argv):
    spec, targets, changed, show_levels = [], [], [], False
    i = 0
    while i < len(argv):
        arg = argv[i]
        i += 1
        if arg == "--levels":
            show_levels = True
        elif arg in ("--target", "--affected") or arg.startswith(("--target=", "--affected=")):
            flag, eq, value = arg.partition("=")
            if not eq:
                if i >= len(argv):
                    raise _Usage(f"option {flag} requires a value")
                value = argv[i]
                i += 1
            (targets if flag == "--target" else changed).append(value)
        elif arg.startswith("-") and arg != "-":
            raise _Usage(f"unknown option {arg}")
        else:
            spec.append(arg)
    if len(spec) != 1:
        raise _Usage("expected exactly one SPEC file")
    if changed and (targets or show_levels):
        raise _Usage("--affected cannot be combined with --target or --levels")
    return spec[0], targets, changed, show_levels


def main(argv=None, out=None, err=None):
    out = out or sys.stdout
    err = err or sys.stderr
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        path, targets, changed, show_levels = _parse_args(argv)
    except _Usage as exc:
        print(f"error: {exc}", file=err)
        return 2
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"error: cannot read {path}: {exc.strerror}", file=err)
        return 2
    try:
        graph = parse_spec(text)
        if changed:
            lines = affected(graph, changed)
        elif show_levels:
            lines = [f"{i}: {' '.join(level)}" for i, level in enumerate(levels(graph, targets or None))]
        else:
            lines = topo_order(graph, targets or None)
    except (GraphError, SpecError) as exc:
        print(f"error: {exc}", file=err)
        return 2
    for line in lines:
        print(line, file=out)
    return 0
