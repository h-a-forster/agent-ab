"""Command line interface."""

import sys

from .graph import GraphError
from .order import topo_order
from .spec import SpecError, parse_spec


def main(argv=None, out=None, err=None):
    out = out or sys.stdout
    err = err or sys.stderr
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("error: expected exactly one SPEC file", file=err)
        return 2
    try:
        with open(argv[0], encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"error: cannot read {argv[0]}: {exc.strerror}", file=err)
        return 2
    try:
        order = topo_order(parse_spec(text))
    except (GraphError, SpecError) as exc:
        print(f"error: {exc}", file=err)
        return 2
    for name in order:
        print(name, file=out)
    return 0
