"""logpipe: a small log-ingestion pipeline."""

from .dedupe import Deduper
from .enrich import Enricher
from .errors import LogpipeError, ParseError, SinkClosed
from .filters import all_of, any_of, min_level, negate
from .parsers import parse_line
from .pipeline import Pipeline
from .sinks import BatchSink, MemorySink
from .timestamps import parse_timestamp
from .windows import aggregate, bucket_start

__all__ = ["Pipeline", "parse_line", "parse_timestamp", "Deduper", "Enricher", "BatchSink", "MemorySink",
           "min_level", "all_of", "any_of", "negate", "aggregate", "bucket_start", "LogpipeError", "ParseError", "SinkClosed"]
