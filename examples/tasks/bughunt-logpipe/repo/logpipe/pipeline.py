"""Putting the stages together."""

from .errors import ParseError
from .parsers import parse_line


class PipelineResult:
    def __init__(self):
        self.read = 0
        self.parsed = 0
        self.errors = []  # (line number, message)
        self.filtered = 0
        self.duplicates = 0
        self.written = 0

    def as_dict(self):
        return {"read": self.read, "parsed": self.parsed, "errors": len(self.errors), "filtered": self.filtered,
                "duplicates": self.duplicates, "written": self.written}

    def __repr__(self):
        return "PipelineResult(%s)" % self.as_dict()


class Pipeline:
    """parse -> filter -> deduplicate -> enrich -> sink.

    Blank lines are skipped without counting.  A line that cannot be parsed is recorded in
    ``result.errors`` with its 1-based line number and processing continues.  The sink is
    closed at the end of ``run`` so that nothing stays buffered.
    """

    def __init__(self, sink, fmt="auto", predicate=None, deduper=None, enricher=None):
        self.sink = sink
        self.fmt = fmt
        self.predicate = predicate
        self.deduper = deduper
        self.enricher = enricher

    def run(self, lines):
        result = PipelineResult()
        try:
            for lineno, line in enumerate(lines, start=1):
                if not line.strip():
                    continue
                result.read += 1
                try:
                    record = parse_line(line, self.fmt, lineno)
                except ParseError as exc:
                    result.errors.append((lineno, str(exc)))
                    continue
                result.parsed += 1
                if self.predicate is not None and not self.predicate(record):
                    result.filtered += 1
                    continue
                if self.deduper is not None and not self.deduper.accept(record):
                    result.duplicates += 1
                    continue
                if self.enricher is not None:
                    self.enricher.enrich(record)
                self.sink.add(record)
                result.written += 1
        finally:
            self.sink.close()
        return result
