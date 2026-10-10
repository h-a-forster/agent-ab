import unittest

from logpipe import (BatchSink, Deduper, Enricher, MemorySink, ParseError, Pipeline, SinkClosed, aggregate,
                     bucket_start, min_level, parse_line, parse_timestamp)
from logpipe import levels
from logpipe.csvout import to_csv
from logpipe.dedupe import default_key
from logpipe.enrich import status_class, subnet, user_agent_family
from logpipe.errors import TimestampError
from logpipe.filters import all_of, any_of, between, field_equals, field_matches, has_field, message_contains, negate
from logpipe.parsers import detect_format
from logpipe.records import Record
from logpipe.redact import mask_cards, mask_email, mask_tokens, redact_record, redact_text
from logpipe.report import format_result, format_windows, level_counts, top_values
from logpipe.sampling import by_key, every_nth, hash_fraction
from logpipe.stats import describe, histogram, mean, percentile
from logpipe.timestamps import format_epoch, parse_offset
from logpipe.windows import rate_per_second, tumbling

BASE = 1710072000  # 2024-03-10T12:00:00Z


def rec(ts, level="INFO", msg="m", host="h", **fields):
    return Record(ts, level, msg, host, fields)


class OffsetSymptoms(unittest.TestCase):
    def test_positive_offsets_subtract(self):
        self.assertEqual(parse_timestamp("2024-03-10T12:00:00+05:30"), BASE - 19800)
        self.assertEqual(parse_timestamp("2024-03-10T12:00:00+01:00"), BASE - 3600)
        self.assertEqual(parse_timestamp("2024-03-10T12:00:00+00:00"), BASE)
        self.assertEqual(parse_timestamp("2024-03-10T12:00:00+14:00"), BASE - 50400)

    def test_negative_offsets_add(self):
        self.assertEqual(parse_timestamp("2024-03-10T12:00:00-08:00"), BASE + 28800)
        self.assertEqual(parse_timestamp("2024-03-10T12:00:00-03:30"), BASE + 12600)

    def test_offset_spellings(self):
        for text, delta in (("+0530", -19800), ("-0800", 28800), ("+05", -18000), ("-11", 39600), ("+05:30", -19800)):
            self.assertEqual(parse_timestamp("2024-03-10T12:00:00" + text), BASE + delta, text)
            self.assertEqual(parse_timestamp("2024-03-10 12:00:00 " + text), BASE + delta, text)

    def test_common_log_format(self):
        self.assertEqual(parse_timestamp("10/Oct/2023:13:55:36 +0200"), 1696946136 - 7200)
        self.assertEqual(parse_timestamp("10/Oct/2023:13:55:36 -0700"), 1696946136 + 25200)
        r = parse_line('1.2.3.4 - - [10/Oct/2023:13:55:36 +0200] "GET /a HTTP/1.1" 200 5')
        self.assertEqual(r.ts, 1696946136 - 7200)

    def test_logfmt_and_json(self):
        r = parse_line("ts=2024-03-10T12:00:05+05:30 level=info msg=hi")
        self.assertEqual(r.ts, BASE + 5 - 19800)
        r = parse_line('{"timestamp": "2024-03-10T12:00:00-08:00", "msg": "x"}')
        self.assertEqual(r.ts, BASE + 28800)

    def test_date_rolls_over(self):
        self.assertEqual(format_epoch(parse_timestamp("2024-03-10T01:30:00+05:30")), "2024-03-09T20:00:00Z")
        self.assertEqual(format_epoch(parse_timestamp("2024-03-10T23:00:00-02:00")), "2024-03-11T01:00:00Z")

    def test_fractions_with_offsets(self):
        self.assertEqual(parse_timestamp("2024-03-10T12:00:00.25+01:00"), BASE - 3600 + 0.25)

    def test_parse_offset_values(self):
        self.assertEqual(parse_offset("+05:30"), 19800)
        self.assertEqual(parse_offset("-0800"), -28800)
        self.assertEqual(parse_offset("Z"), 0)
        self.assertEqual(parse_offset(None), 0)
        with self.assertRaises(TimestampError):
            parse_offset("+25:00")

    def test_mixed_offsets_sort_correctly(self):
        a = parse_timestamp("2024-03-10T12:00:00+02:00")  # 10:00Z
        b = parse_timestamp("2024-03-10T11:00:00Z")
        c = parse_timestamp("2024-03-10T06:00:00-05:00")  # 11:00Z
        self.assertEqual(sorted([c, b, a]), [a, b, c])
        self.assertEqual(b, c)


class PercentileSymptoms(unittest.TestCase):
    def test_nearest_rank_small(self):
        data = [4, 1, 3, 2]
        self.assertEqual(percentile(data, 25), 1)
        self.assertEqual(percentile(data, 50), 2)
        self.assertEqual(percentile(data, 75), 3)
        self.assertEqual(percentile(data, 100), 4)
        self.assertEqual(percentile(data, 95), 4)
        self.assertEqual(percentile(data, 1), 1)

    def test_larger_sets(self):
        data = list(range(1, 21))
        self.assertEqual(percentile(data, 95), 19)
        self.assertEqual(percentile(data, 50), 10)
        self.assertEqual(percentile(data, 90), 18)
        data = list(range(1, 101))
        self.assertEqual([percentile(data, p) for p in (1, 50, 90, 95, 99, 100)], [1, 50, 90, 95, 99, 100])
        self.assertEqual(percentile(list(range(1, 11)), 50), 5)
        self.assertEqual(percentile(list(range(1, 11)), 90), 9)

    def test_odd_and_tiny(self):
        self.assertEqual(percentile([7], 1), 7)
        self.assertEqual(percentile([7], 100), 7)
        self.assertEqual(percentile([1, 2, 3], 50), 2)
        self.assertEqual(percentile([1, 2, 3], 34), 2)
        self.assertEqual(percentile([1, 2, 3], 33), 1)
        self.assertEqual(percentile([5, 5, 5, 9], 75), 5)

    def test_describe(self):
        d = describe(list(range(1, 101)))
        self.assertEqual((d["p50"], d["p95"], d["p99"], d["min"], d["max"], d["mean"]), (50, 95, 99, 1, 100, 50.5))
        d = describe([10, 20, 30, 40])
        self.assertEqual((d["p50"], d["p95"], d["count"]), (20, 40, 4))

    def test_window_latency_rows(self):
        records = [rec(i, latency_ms=v) for i, v in enumerate([40, 10, 30, 20])]
        (row,) = aggregate(records, 60)
        self.assertEqual((row["latency"]["p50"], row["latency"]["p95"], row["latency"]["p99"]), (20, 40, 40))


class WindowSymptoms(unittest.TestCase):
    def test_second_half_of_window(self):
        self.assertEqual(bucket_start(59.6, 60), 0)
        self.assertEqual(bucket_start(31, 60), 0)
        self.assertEqual(bucket_start(45, 60), 0)
        self.assertEqual(bucket_start(59, 60), 0)
        self.assertEqual(bucket_start(90, 60), 60)
        self.assertEqual(bucket_start(89.9, 60), 60)
        self.assertEqual(bucket_start(119, 60), 60)
        self.assertEqual(bucket_start(3599, 3600), 0)
        self.assertEqual(bucket_start(5400, 3600), 3600)

    def test_edges_and_negatives(self):
        self.assertEqual(bucket_start(0, 60), 0)
        self.assertEqual(bucket_start(60, 60), 60)
        self.assertEqual(bucket_start(-1, 60), -60)
        self.assertEqual(bucket_start(-60, 60), -60)
        self.assertEqual(bucket_start(-61, 60), -120)
        self.assertEqual(bucket_start(BASE + 59, 60), BASE)
        self.assertEqual(bucket_start(7.5, 5), 5)

    def test_types(self):
        self.assertIsInstance(bucket_start(59.6, 60), int)
        self.assertIsInstance(bucket_start(100, 60), int)
        self.assertEqual(bucket_start(1.5, 0.5), 1.5)

    def test_tumbling_groups(self):
        records = [rec(t) for t in (10, 40, 59.6, 61, 119.9, 125)]
        groups = tumbling(records, 60)
        self.assertEqual(list(groups), [0, 60, 120])
        self.assertEqual([[r.ts for r in g] for g in groups.values()], [[10, 40, 59.6], [61, 119.9], [125]])

    def test_aggregate_rows(self):
        records = [rec(1, "INFO"), rec(35, "ERROR"), rec(59.9, "FATAL"), rec(61, "WARN"), rec(100, "DEBUG")]
        rows = aggregate(records, 60)
        self.assertEqual([(r["start"], r["end"], r["count"], r["errors"]) for r in rows], [(0, 60, 3, 2), (60, 120, 2, 0)])
        self.assertEqual(rows[0]["levels"], {"INFO": 1, "ERROR": 1, "FATAL": 1})
        self.assertEqual(rows[1]["levels"], {"DEBUG": 1, "WARN": 1})

    def test_rate_and_format(self):
        rows = aggregate([rec(BASE + 40), rec(BASE + 50), rec(BASE + 70)], 60)
        self.assertEqual(rate_per_second(rows), [(BASE, 2 / 60), (BASE + 60, 1 / 60)])
        self.assertEqual(format_windows(rows), "2024-03-10T12:00:00Z count=2 errors=0\n2024-03-10T12:01:00Z count=1 errors=0")

    def test_bad_size(self):
        with self.assertRaises(ValueError):
            tumbling([rec(1)], 0)


class DedupeSymptoms(unittest.TestCase):
    def test_steady_stream_lets_one_through_per_window(self):
        d = Deduper(10)
        accepted = [t for t in range(0, 41, 4) if d.accept(rec(t))]
        self.assertEqual(accepted, [0, 12, 24, 36])
        self.assertEqual(d.dropped, 7)

    def test_dropped_records_do_not_extend_window(self):
        d = Deduper(10)
        self.assertTrue(d.accept(rec(0)))
        self.assertFalse(d.accept(rec(9)))
        self.assertTrue(d.accept(rec(10)))
        self.assertFalse(d.accept(rec(19)))
        self.assertTrue(d.accept(rec(20)))

    def test_exact_window_passes(self):
        d = Deduper(5)
        self.assertTrue(d.accept(rec(0)))
        self.assertFalse(d.accept(rec(4.99)))
        self.assertTrue(d.accept(rec(5)))

    def test_pipeline_counts(self):
        sink = MemorySink(batch_size=10)
        lines = ["ts=%d level=info msg=tick host=a" % (BASE + t) for t in range(0, 31, 5)]
        result = Pipeline(sink, deduper=Deduper(12)).run(lines)
        self.assertEqual((result.written, result.duplicates), (3, 4))
        self.assertEqual([r.ts - BASE for r in sink.records()], [0, 15, 30])

    def test_keys_are_independent(self):
        d = Deduper(10)
        self.assertTrue(d.accept(rec(0, msg="a")))
        self.assertTrue(d.accept(rec(1, msg="b")))
        self.assertTrue(d.accept(rec(2, msg="a", host="other")))
        self.assertFalse(d.accept(rec(3, msg="a")))
        self.assertEqual(d.tracked(), 3)
        self.assertEqual(default_key(rec(0, msg="x", host="y")), ("y", "x"))

    def test_custom_key_and_reset(self):
        d = Deduper(10, key=lambda r: r.get("path"))
        self.assertTrue(d.accept(rec(0, path="/a")))
        self.assertFalse(d.accept(rec(2, path="/a", msg="other")))
        d.reset()
        self.assertTrue(d.accept(rec(3, path="/a")))
        self.assertEqual(d.dropped, 0)
        with self.assertRaises(ValueError):
            Deduper(0)


class SinkSymptoms(unittest.TestCase):
    def test_close_flushes_remainder(self):
        sink = MemorySink(batch_size=2)
        for i in range(5):
            sink.add(rec(i))
        self.assertEqual(sink.pending(), 1)
        sink.close()
        self.assertEqual([len(b) for b in sink.batches_written], [2, 2, 1])
        self.assertEqual(sink.written, 5)
        self.assertEqual(sink.pending(), 0)
        self.assertTrue(sink.closed)

    def test_context_manager(self):
        out = []
        with BatchSink(out.append, batch_size=3) as sink:
            for i in range(4):
                sink.add(rec(i))
        self.assertEqual([len(b) for b in out], [3, 1])
        self.assertEqual((sink.batches, sink.written), (2, 4))

    def test_close_twice_and_empty(self):
        out = []
        sink = BatchSink(out.append, 5)
        sink.close()
        sink.close()
        self.assertEqual(out, [])
        sink2 = BatchSink(out.append, 5)
        sink2.add(rec(1))
        sink2.close()
        sink2.close()
        self.assertEqual(len(out), 1)

    def test_pipeline_leaves_nothing_behind(self):
        sink = MemorySink(batch_size=2)
        lines = ["ts=%d level=info msg=m%d" % (BASE + i, i) for i in range(5)]
        result = Pipeline(sink).run(lines)
        self.assertEqual(result.written, 5)
        self.assertEqual(len(sink.records()), 5)
        self.assertEqual([r.msg for r in sink.records()], ["m0", "m1", "m2", "m3", "m4"])

    def test_pipeline_single_record_and_batch_larger_than_input(self):
        sink = MemorySink(batch_size=100)
        Pipeline(sink).run(["ts=%d msg=only" % BASE])
        self.assertEqual([r.msg for r in sink.records()], ["only"])
        sink = MemorySink(batch_size=100)
        Pipeline(sink).run(["ts=%d msg=%d" % (BASE, i) for i in range(7)])
        self.assertEqual(len(sink.records()), 7)

    def test_sink_closed_even_if_a_filter_raises(self):
        out = []
        sink = BatchSink(out.append, 10)

        def boom(record):
            if record.msg == "bad":
                raise RuntimeError("boom")
            return True

        with self.assertRaises(RuntimeError):
            Pipeline(sink, predicate=boom).run(["ts=%d msg=ok" % BASE, "ts=%d msg=bad" % BASE])
        self.assertTrue(sink.closed)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]), 1)

    def test_add_after_close(self):
        sink = MemorySink(2)
        sink.close()
        with self.assertRaises(SinkClosed):
            sink.add(rec(0))


class LevelSymptoms(unittest.TestCase):
    def keep(self, minimum, level):
        return min_level(minimum)(rec(0, level))

    def test_warn_keeps_more_severe(self):
        for level, expected in (("DEBUG", False), ("INFO", False), ("WARN", True), ("ERROR", True), ("FATAL", True)):
            self.assertEqual(self.keep("WARN", level), expected, level)

    def test_other_thresholds(self):
        for level, expected in (("DEBUG", False), ("INFO", False), ("WARN", False), ("ERROR", True), ("FATAL", True)):
            self.assertEqual(self.keep("ERROR", level), expected, level)
        for level, expected in (("DEBUG", False), ("INFO", True), ("WARN", True), ("ERROR", True), ("FATAL", True)):
            self.assertEqual(self.keep("INFO", level), expected, level)
        for level, expected in (("DEBUG", False), ("INFO", False), ("WARN", False), ("ERROR", False), ("FATAL", True)):
            self.assertEqual(self.keep("FATAL", level), expected, level)
        for level in levels.ORDER:
            self.assertTrue(self.keep("DEBUG", level))

    def test_aliases_and_case(self):
        self.assertTrue(self.keep("warning", "ERROR"))
        self.assertTrue(self.keep("Warn", "FATAL"))
        self.assertFalse(self.keep("critical", "ERROR"))
        self.assertTrue(self.keep("fatal", "FATAL"))
        with self.assertRaises(ParseError):
            min_level("loud")

    def test_pipeline_with_levels(self):
        lines = ['{"ts": "%s", "level": "%s", "msg": "%s"}' % ("2024-03-10T12:00:00Z", lvl, lvl.lower())
                 for lvl in ("debug", "info", "warning", "error", "critical")]
        sink = MemorySink(10)
        result = Pipeline(sink, predicate=min_level("WARN")).run(lines)
        self.assertEqual([r.level for r in sink.records()], ["WARN", "ERROR", "FATAL"])
        self.assertEqual((result.filtered, result.written), (2, 3))

    def test_combinators_with_levels(self):
        keep = all_of(min_level("ERROR"), negate(field_equals("host", "db")))
        self.assertTrue(keep(rec(0, "FATAL", host="web")))
        self.assertFalse(keep(rec(0, "FATAL", host="db")))
        self.assertFalse(keep(rec(0, "WARN", host="web")))
        either = any_of(min_level("FATAL"), message_contains("disk"))
        self.assertTrue(either(rec(0, "DEBUG", msg="Disk full")))
        self.assertTrue(either(rec(0, "FATAL", msg="x")))
        self.assertFalse(either(rec(0, "ERROR", msg="x")))

    def test_http_status_levels_through_filter(self):
        lines = ['1.1.1.1 - - [10/Oct/2023:13:55:36 +0000] "GET /%s HTTP/1.1" %d 1' % (p, s) for p, s in (("a", 200), ("b", 404), ("c", 503))]
        sink = MemorySink(10)
        Pipeline(sink, predicate=min_level("WARN")).run(lines)
        self.assertEqual([r.msg for r in sink.records()], ["GET /b", "GET /c"])
        sink = MemorySink(10)
        Pipeline(sink, predicate=min_level("ERROR")).run(lines)
        self.assertEqual([r.msg for r in sink.records()], ["GET /c"])


class EnrichSymptoms(unittest.TestCase):
    def test_records_get_their_own_fields(self):
        e = Enricher({"env": "prod"})
        r1 = e.enrich(rec(0, ip="10.1.2.3", status=200))
        r2 = e.enrich(rec(1, ip="192.168.0.9", status=404, extra="x"))
        self.assertEqual(r1.fields, {"env": "prod", "ip": "10.1.2.3", "status": 200, "subnet": "10.1.2.0/24", "status_class": "2xx"})
        self.assertEqual(r2.fields["subnet"], "192.168.0.0/24")
        self.assertIsNot(r1.fields, r2.fields)
        self.assertNotIn("extra", r1.fields)

    def test_defaults_untouched(self):
        defaults = {"env": "prod"}
        e = Enricher(defaults)
        e.enrich(rec(0, ip="1.2.3.4", other=1))
        e.enrich(rec(1, status=500))
        self.assertEqual(e.defaults, {"env": "prod"})
        self.assertEqual(defaults, {"env": "prod"})

    def test_record_fields_win_and_originals_not_aliased(self):
        e = Enricher({"env": "prod", "team": "core"})
        r = rec(0, env="staging")
        out = e.enrich(r)
        self.assertEqual(out.fields, {"env": "staging", "team": "core"})
        out.fields["team"] = "changed"
        self.assertEqual(e.defaults["team"], "core")
        self.assertEqual(e.enrich(rec(1)).fields, {"env": "prod", "team": "core"})

    def test_no_leak_between_records_in_pipeline(self):
        sink = MemorySink(10)
        lines = ['{"ts": "2024-03-10T12:00:0%dZ", "msg": "m", %s}' % (i, extra) for i, extra in
                 enumerate(['"ip": "10.0.0.1", "only_first": 1', '"status": 404', '"ip": "172.16.5.4"'])]
        Pipeline(sink, enricher=Enricher({"env": "x"})).run(lines)
        a, b, c = sink.records()
        self.assertEqual(a.fields, {"env": "x", "ip": "10.0.0.1", "only_first": 1, "subnet": "10.0.0.0/24"})
        self.assertEqual(b.fields, {"env": "x", "status": 404, "status_class": "4xx"})
        self.assertEqual(c.fields, {"env": "x", "ip": "172.16.5.4", "subnet": "172.16.5.0/24"})

    def test_default_enricher_without_defaults(self):
        e = Enricher()
        r1 = e.enrich(rec(0, a=1))
        r2 = e.enrich(rec(1, b=2))
        self.assertEqual(r1.fields, {"a": 1})
        self.assertEqual(r2.fields, {"b": 2})
        self.assertEqual(e.defaults, {})

    def test_prefix_option(self):
        e = Enricher(prefix=16)
        self.assertEqual(e.enrich(rec(0, ip="10.1.2.3")).fields["subnet"], "10.1.0.0/16")


class ParserRegression(unittest.TestCase):
    def test_clf_variants(self):
        r = parse_line('9.9.9.9 - bob [10/Oct/2023:13:55:36 +0000] "POST /x?y=1 HTTP/2" 503 - 250')
        self.assertEqual((r.level, r.msg, r.fields["user"], r.fields["bytes"], r.fields["latency_ms"], r.fields["status"]),
                         ("ERROR", "POST /x?y=1", "bob", 0, 250.0, 503))
        r = parse_line('9.9.9.9 - - [10/Oct/2023:13:55:36 +0000] "GET / HTTP/1.1" 301 12')
        self.assertEqual((r.level, r.fields["user"], "latency_ms" in r.fields), ("INFO", None, False))
        r = parse_line('9.9.9.9 - - [10/Oct/2023:13:55:36 +0000] "GET / HTTP/1.1" 404 0')
        self.assertEqual(r.level, "WARN")

    def test_json_key_variants(self):
        r = parse_line('{"@timestamp": "2024-03-10T12:00:00Z", "severity": "ERR", "message": "boom", "host": "h1", "a": {"b": 1}}')
        self.assertEqual((r.ts, r.level, r.msg, r.host, r.fields), (BASE, "ERROR", "boom", "h1", {"a": {"b": 1}}))
        r = parse_line('{"time": 1710072000, "msg": 5}')
        self.assertEqual((r.ts, r.level, r.msg), (BASE, "INFO", "5"))

    def test_logfmt_details(self):
        r = parse_line('ts=%d level=WARNING msg="quoted \\"x\\" here" host=h n=3 f=1.5 s=abc q="12"' % BASE)
        self.assertEqual((r.level, r.msg, r.host), ("WARN", 'quoted "x" here', "h"))
        self.assertEqual(r.fields, {"n": 3, "f": 1.5, "s": "abc", "q": "12"})

    def test_detect_and_unknown_format(self):
        self.assertEqual(detect_format('{"a": 1}'), "json")
        self.assertEqual(detect_format("ts=1 msg=x"), "logfmt")
        self.assertEqual(detect_format("level=info msg=x"), "logfmt")
        self.assertEqual(detect_format('1.1.1.1 - - [x] "GET / HTTP/1.1" 200 1'), "clf")
        with self.assertRaises(ParseError):
            parse_line("x", fmt="xml")

    def test_forced_format_and_raw(self):
        r = parse_line("ts=%d msg=x\n" % BASE, fmt="logfmt", lineno=3)
        self.assertEqual((r.raw, r.lineno), ("ts=%d msg=x" % BASE, 3))
        with self.assertRaises(ParseError):
            parse_line("ts=%d msg=x" % BASE, fmt="json")

    def test_errors(self):
        for line in ("", "no equals here", '{"msg": "x"}', "ts=notatime msg=x", '{"ts": "2024-99-99T00:00:00Z"}', "level=info msg=x"):
            with self.assertRaises(ParseError, msg=line):
                parse_line(line)

    def test_timestamp_forms(self):
        self.assertEqual(parse_timestamp("1710072000.5"), 1710072000.5)
        self.assertEqual(parse_timestamp(" 2024-03-10T12:00:00Z "), BASE)
        self.assertEqual(parse_timestamp("2024-03-10T12:00:00z"), BASE)
        self.assertEqual(parse_timestamp("1970-01-01T00:00:00Z"), 0)
        self.assertEqual(parse_timestamp("1969-12-31T23:59:59Z"), -1)
        self.assertEqual(parse_timestamp("2024-02-29T00:00:00Z"), 1709164800)
        self.assertEqual(format_epoch(0), "1970-01-01T00:00:00Z")
        self.assertEqual(format_epoch(1710072000.9), "2024-03-10T12:00:00Z")
        for bad in ("", "tomorrow", "2024-03-10", "10/Foo/2023:13:55:36 +0000"):
            with self.assertRaises(TimestampError, msg=bad):
                parse_timestamp(bad)


class LevelsAndFiltersRegression(unittest.TestCase):
    def test_levels(self):
        self.assertEqual([levels.parse_level(x) for x in ("debug", "Info", "WARNING", "err", "crit", "notice", "trace")],
                         ["DEBUG", "INFO", "WARN", "ERROR", "FATAL", "INFO", "DEBUG"])
        self.assertEqual(levels.parse_level("weird", default="INFO"), "INFO")
        self.assertEqual(levels.parse_level(None, default="WARN"), "WARN")
        with self.assertRaises(ParseError):
            levels.parse_level("weird")
        with self.assertRaises(ParseError):
            levels.parse_level("")
        self.assertEqual([levels.rank(x) for x in levels.ORDER], [0, 1, 2, 3, 4])
        self.assertTrue(levels.at_least("FATAL", "debug"))
        self.assertFalse(levels.at_least("INFO", "ERROR"))
        self.assertEqual([levels.from_status(s) for s in (200, 399, 400, 499, 500, 599)], ["INFO", "INFO", "WARN", "WARN", "ERROR", "ERROR"])

    def test_predicates(self):
        r = rec(100, msg="Disk Full", host="web1", path="/api/v1/x", n=0)
        self.assertTrue(message_contains("disk")(r))
        self.assertFalse(message_contains("disk", case_sensitive=True)(r))
        self.assertTrue(field_matches("path", r"^/api/v\d+/")(r))
        self.assertFalse(field_matches("missing", "x")(r))
        self.assertTrue(has_field("n")(r))
        self.assertFalse(has_field("zzz")(r))
        self.assertTrue(field_equals("host", "web1")(r))
        self.assertTrue(between(100, 101)(r))
        self.assertFalse(between(0, 100)(r))
        self.assertEqual(r.get("host"), "web1")
        self.assertEqual(r.get("zzz", 5), 5)
        self.assertEqual(r.as_dict()["path"], "/api/v1/x")

    def test_pipeline_result_and_errors(self):
        sink = MemorySink(3)
        lines = ["ts=%d msg=a" % BASE, "", "   ", "nonsense", "ts=%d level=debug msg=b" % BASE, '{"oops"']
        result = Pipeline(sink, predicate=min_level("INFO")).run(lines)
        self.assertEqual(result.as_dict(), {"read": 4, "parsed": 2, "errors": 2, "filtered": 1, "duplicates": 0, "written": 1})
        self.assertEqual([n for n, _ in result.errors], [4, 6])
        text = format_result(result)
        self.assertTrue(text.startswith("read 4, parsed 2, written 1\nfiltered 1, duplicates 0, errors 2\n  line 4: "))

    def test_report_helpers(self):
        records = [rec(0, "ERROR", host="a"), rec(1, "INFO", host="b"), rec(2, "ERROR", host="a"), rec(3, "DEBUG", host="c"), rec(4, "INFO", host="b")]
        self.assertEqual(level_counts(records), {"DEBUG": 1, "INFO": 2, "ERROR": 2})
        self.assertEqual(top_values(records, "host", 2), [("a", 2), ("b", 2)])
        self.assertEqual(top_values(records, "missing"), [])


class StatsMiscRegression(unittest.TestCase):
    def test_mean_histogram_errors(self):
        self.assertEqual(mean([1, 2, 3, 6]), 3.0)
        self.assertEqual(histogram([0, 1, 5, 9, 10, 11, -1], [0, 5, 10]), [2, 3])
        for call in (lambda: percentile([], 50), lambda: percentile([1], 0), lambda: percentile([1], 101), lambda: mean([])):
            with self.assertRaises(ValueError):
                call()

    def test_enrich_helpers(self):
        self.assertEqual(subnet("10.1.2.3", 16), "10.1.0.0/16")
        self.assertEqual(subnet("10.1.2.3", 8), "10.0.0.0/8")
        self.assertIsNone(subnet("10.1.2.300"))
        self.assertIsNone(subnet("::1"))
        self.assertIsNone(subnet("10.1.2.3", 12))
        self.assertEqual([status_class(x) for x in (200, "404", 599, 99, 600, "x", None)], ["2xx", "4xx", "5xx", None, None, None, None])
        self.assertEqual([user_agent_family(x) for x in ("Mozilla Firefox/99", "Chrome/1 Safari/2", "curl/8", "wget")],
                         ["firefox", "chrome", "curl", "other"])

    def test_agent_field(self):
        r = Enricher().enrich(rec(0, agent="Mozilla/5.0 Chrome/120"))
        self.assertEqual(r.fields["agent_family"], "chrome")

    def test_redact(self):
        self.assertEqual(mask_email("mail bob.smith@example.com now"), "mail ***@example.com now")
        self.assertEqual(mask_tokens("login password=hunter2 token=abc&x=1"), "login password=[redacted] token=[redacted]&x=1")
        self.assertEqual(mask_cards("card 4111 1111 1111 1111 ok"), "card ************1111 ok")
        self.assertEqual(mask_cards("order 12345 ships"), "order 12345 ships")
        self.assertEqual(redact_text("a@b.io password=x 4111111111111111"), "***@b.io password=[redacted] ************1111")
        r = redact_record(rec(0, msg="user a@b.io", note="token=zzz", n=5), fields=("note", "n"))
        self.assertEqual((r.msg, r.fields), ("user ***@b.io", {"note": "token=[redacted]", "n": 5}))

    def test_sampling(self):
        keep = every_nth(3)
        self.assertEqual([i for i in range(10) if keep(rec(i))], [0, 3, 6, 9])
        self.assertEqual(hash_fraction("abc"), hash_fraction("abc"))
        self.assertTrue(0 <= hash_fraction("anything") < 1)
        pred = by_key("host", 0.5)
        hosts = ["h%d" % i for i in range(200)]
        kept = [h for h in hosts if pred(rec(0, host=h))]
        self.assertEqual(kept, [h for h in hosts if pred(rec(5, host=h))])
        self.assertTrue(60 < len(kept) < 140)
        self.assertFalse(by_key("nofield", 1.0)(rec(0)))
        self.assertTrue(by_key("host", 1.0)(rec(0, host="x")))
        with self.assertRaises(ValueError):
            every_nth(0)
        with self.assertRaises(ValueError):
            by_key("host", 2)

    def test_csv(self):
        records = [rec(1, "INFO", 'say "hi", ok', "h1", b=2, a=None), rec(2, "ERROR", "x", None, c=3)]
        self.assertEqual(to_csv(records), 'ts,level,msg,host,a,b,c\n1,INFO,"say ""hi"", ok",h1,,2,\n2,ERROR,x,,,,3\n')
        self.assertEqual(to_csv(records, ["level", "host"]), "level,host\nINFO,h1\nERROR,\n")


if __name__ == "__main__":
    unittest.main()
