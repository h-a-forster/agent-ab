"""Where records end up."""

from .errors import SinkClosed


class BatchSink:
    """Collects records and hands them to ``write(batch)`` in batches of ``batch_size``.

    A full batch is written as soon as it is complete; ``flush()`` writes what is buffered;
    ``close()`` flushes the remaining records and then refuses further records.  Usable as a
    context manager (closing on exit).
    """

    def __init__(self, write, batch_size=100):
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self.write = write
        self.batch_size = batch_size
        self._buffer = []
        self.batches = 0
        self.written = 0
        self.closed = False

    def add(self, record):
        if self.closed:
            raise SinkClosed("sink is closed")
        self._buffer.append(record)
        if len(self._buffer) >= self.batch_size:
            self.flush()

    def flush(self):
        if not self._buffer:
            return 0
        batch = list(self._buffer)
        self._buffer.clear()
        self.write(batch)
        self.batches += 1
        self.written += len(batch)
        return len(batch)

    def pending(self):
        return len(self._buffer)

    def close(self):
        if not self.closed:
            self._buffer.clear()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class MemorySink(BatchSink):
    """A BatchSink that keeps every written batch in ``self.batches_written``."""

    def __init__(self, batch_size=100):
        self.batches_written = []
        super().__init__(self.batches_written.append, batch_size)

    def records(self):
        return [r for batch in self.batches_written for r in batch]
