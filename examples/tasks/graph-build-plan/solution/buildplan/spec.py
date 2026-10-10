"""The spec file format: ``name: dep ?optional_dep ...`` per line, ``#`` comments."""

import re

from .graph import Graph

_NAME = re.compile(r"^[A-Za-z0-9_.+/@-]+$")


class SpecError(ValueError):
    pass


def parse_spec(text):
    graph = Graph()
    seen = set()
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name, colon, rest = line.partition(":")
        name = name.strip()
        if not colon:
            raise SpecError(f"line {number}: expected 'name: deps'")
        if not _NAME.match(name):
            raise SpecError(f"line {number}: invalid name {name!r}")
        if name in seen:
            raise SpecError(f"line {number}: duplicate node {name!r}")
        seen.add(name)
        graph.add_node(name)
        for token in rest.split():
            optional = token.startswith("?")
            dep = token[1:] if optional else token
            if not _NAME.match(dep):
                raise SpecError(f"line {number}: invalid name {token!r}")
            graph.add_dep(name, dep, optional=optional)
    return graph
