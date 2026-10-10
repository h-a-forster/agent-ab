import unittest

from logpipe import (BatchSink, Deduper, Enricher, MemorySink, ParseError, Pipeline, SinkClosed, aggregate,
                     bucket_start, min_level, parse_line, parse_timestamp)
from logpipe.enrich import status_class, subnet
from logpipe.filters import all_of, field_equals, message_contains, negate
from logpipe.records import Record
from logpipe.stats import describe, percentile
from logpipe.timestamps import format_epoch

CLF = '203.0.113.9 - alice [10/Oct/2023:13:55:36 +0000] "GET /index.html HTTP/1.1" 200 2326 12.5'
JSONL = '{"ts": "2024-03-10T12:00:00Z", "level": "warning", "msg": "disk low", "host": "web1", "free_gb": 3}'
LOGFMT = 'ts=2024-03-10T12:00:05Z level=error msg="db timeout" host=db1 retries=3'


def rec(ts, level="INFO", msg="m", host="h", **fields):
    return Record(ts, level, msg, host, fields)


class TimestampTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(parse_timestamp("2024-03-10T12:00:00Z"), 1710072000)
        self.assertEqual(parse_timestamp("2024-03-10 12:00:00"), 1710072000)
        self.assertEqual(parse_timestamp("2024-03-10T12:00:00+00:00"), 1710072000)
        self.assertEqual(parse_timestamp("2024-03-10T12:00:00.5Z"), 1710072000.5)
        self.assertEqual(parse_timestamp("1710072000"), 1710072000)
        self.assertEqual(parse_timestamp("10/Oct/2023:13:55:36 +0000"), 1696946136)
        self.assertEqual(format_epoch(1710072000), "2024-03-10T12:00:00Z")

    def test_errors(self):
        for bad in ("yesterday", "2024-13-10T00:00:00Z", "2024-03-10T25:00:00Z"):
            with self.assertRaises(Exception):
                parse_timestamp(bad)


class ParserTests(unittest.TestCase):
    def test_clf(self):
        r = parse_line(CLF)
        self.assertEqual((r.ts, r.level, r.msg, r.host), (1696946136, "INFO", "GET /index.html", "203.0.113.9"))
        self.assertEqual(r.fields["status"], 200)
        self.assertEqual(r.fields["latency_ms"], 12.5)

    def test_json_and_logfmt(self):
        r = parse_line(JSONL)
        self.assertEqual((r.level, r.msg, r.host, r.fields), ("WARN", "disk low", "web1", {"free_gb": 3}))
        r = parse_line(LOGFMT, lineno=7)
        self.assertEqual((r.level, r.msg, r.host, r.fields, r.lineno), ("ERROR", "db timeout", "db1", {"retries": 3}, 7))

    def test_errors(self):
        for bad in ("garbage", "{not json", "[1, 2]", '{"msg": "no time"}'):
            with self.assertRaises(ParseError):
                parse_line(bad)


class FilterStatsTests(unittest.TestCase):
    def test_filters(self):
        keep = all_of(min_level("DEBUG"), message_contains("DISK"), negate(field_equals("host", "x")))
        self.assertTrue(keep(rec(0, msg="disk low")))
        self.assertFalse(keep(rec(0, msg="disk low", host="x")))

    def test_stats(self):
        self.assertEqual(percentile([5, 1, 3, 2, 4], 100), 5)
        self.assertEqual(describe([2, 4])["mean"], 3)
        self.assertEqual(describe([])["count"], 0)

    def test_enrich_helpers(self):
        self.assertEqual(subnet("10.1.2.3"), "10.1.2.0/24")
        self.assertEqual(status_class(404), "4xx")


class WindowTests(unittest.TestCase):
    def test_bucket_start(self):
        self.assertEqual(bucket_start(10, 60), 0)
        self.assertEqual(bucket_start(70, 60), 60)
        self.assertEqual(bucket_start(125, 60), 120)

    def test_aggregate(self):
        rows = aggregate([rec(1, "INFO", latency_ms=10), rec(5, "ERROR", latency_ms=30), rec(65, "WARN")], 60)
        self.assertEqual([(r["start"], r["count"], r["errors"]) for r in rows], [(0, 2, 1), (60, 1, 0)])
        self.assertEqual(rows[0]["latency"]["max"], 30)


class DedupeSinkEnrichTests(unittest.TestCase):
    def test_dedupe(self):
        d = Deduper(10)
        self.assertTrue(d.accept(rec(0)))
        self.assertFalse(d.accept(rec(5)))
        self.assertTrue(d.accept(rec(30)))
        self.assertTrue(d.accept(rec(5, host="other")))

    def test_sink(self):
        sink = MemorySink(batch_size=2)
        for i in range(4):
            sink.add(rec(i))
        self.assertEqual([len(b) for b in sink.batches_written], [2, 2])
        sink.add(rec(9))
        self.assertEqual(sink.flush(), 1)
        sink.close()
        with self.assertRaises(SinkClosed):
            sink.add(rec(10))

    def test_enrich_one(self):
        r = Enricher({"env": "prod"}).enrich(rec(0, ip="10.1.2.3", status=503))
        self.assertEqual(r.fields, {"env": "prod", "ip": "10.1.2.3", "status": 503, "subnet": "10.1.2.0/24", "status_class": "5xx"})

    def test_pipeline(self):
        sink = MemorySink(batch_size=2)
        lines = [CLF, "", "garbage", JSONL, LOGFMT, CLF.replace("200", "404")]
        result = Pipeline(sink, predicate=min_level("DEBUG")).run(lines)
        self.assertEqual(result.as_dict(), {"read": 5, "parsed": 4, "errors": 1, "filtered": 0, "duplicates": 0, "written": 4})
        self.assertEqual(result.errors[0][0], 3)
        self.assertEqual(len(sink.records()), 4)


if __name__ == "__main__":
    unittest.main()
