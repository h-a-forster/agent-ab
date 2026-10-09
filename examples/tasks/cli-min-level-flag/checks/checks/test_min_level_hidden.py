import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from levelcount import main

SAMPLE = """\
2024-05-01T10:00:00 INFO started
2024-05-01T10:00:01 debug cache warm
2024-05-01T10:00:02 [warn] slow request
2024-05-01T10:00:03 ERROR boom
2024-05-01T10:00:04 INFO done
2024-05-01T10:00:05 fatal out of memory
2024-05-01T10:00:06 WARNING retrying
2024-05-01T10:00:07 err again
not a log line
"""


class MinLevelTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".log")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(SAMPLE)

    def tearDown(self):
        os.remove(self.path)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def table(self, out):
        return [line.split() for line in out.strip().splitlines()]

    def test_default_unchanged(self):
        code, out, _ = self.run_cli(self.path)
        self.assertEqual(code, 0)
        self.assertEqual(
            self.table(out),
            [["DEBUG", "1"], ["INFO", "2"], ["WARNING", "2"], ["ERROR", "2"], ["CRITICAL", "1"], ["TOTAL", "8"]],
        )

    def test_min_level_warning_table(self):
        code, out, _ = self.run_cli("--min-level", "warning", self.path)
        self.assertEqual(code, 0)
        self.assertEqual(
            self.table(out), [["WARNING", "2"], ["ERROR", "2"], ["CRITICAL", "1"], ["TOTAL", "5"]]
        )

    def test_short_option_and_equals_form(self):
        _, out_short, _ = self.run_cli("-m", "ERROR", self.path)
        _, out_eq, _ = self.run_cli("--min-level=error", self.path)
        expected = [["ERROR", "2"], ["CRITICAL", "1"], ["TOTAL", "3"]]
        self.assertEqual(self.table(out_short), expected)
        self.assertEqual(self.table(out_eq), expected)

    def test_aliases(self):
        _, out_warn, _ = self.run_cli("--min-level", "WARN", self.path)
        self.assertEqual(self.table(out_warn)[-1], ["TOTAL", "5"])
        _, out_fatal, _ = self.run_cli("--min-level", "Fatal", self.path)
        self.assertEqual(self.table(out_fatal), [["CRITICAL", "1"], ["TOTAL", "1"]])
        _, out_err, _ = self.run_cli("-m", "err", self.path)
        self.assertEqual(self.table(out_err)[-1], ["TOTAL", "3"])

    def test_json_respects_min_level(self):
        code, out, _ = self.run_cli("--json", "--min-level", "info", self.path)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data, {"INFO": 2, "WARNING": 2, "ERROR": 2, "CRITICAL": 1})
        self.assertEqual(list(data), ["INFO", "WARNING", "ERROR", "CRITICAL"])

    def test_debug_is_everything(self):
        _, out_all, _ = self.run_cli(self.path)
        _, out_debug, _ = self.run_cli("-m", "debug", self.path)
        self.assertEqual(out_all, out_debug)

    def test_nothing_at_level(self):
        fd, path = tempfile.mkstemp(suffix=".log")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("t INFO a\nt DEBUG b\n")
        try:
            code, out, _ = self.run_cli("--min-level", "error", path)
            self.assertEqual(code, 0)
            self.assertEqual(self.table(out), [["TOTAL", "0"]])
            _, out_json, _ = self.run_cli("--json", "--min-level", "error", path)
            self.assertEqual(json.loads(out_json), {})
        finally:
            os.remove(path)

    def test_unknown_level_is_usage_error(self):
        code, out, err = self.run_cli("--min-level", "loud", self.path)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("loud", err.lower())
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            self.assertIn(level, err)

    def test_help_mentions_option(self):
        code, out, _ = self.run_cli("--help")
        self.assertEqual(code, 0)
        self.assertIn("--min-level", out)
        self.assertIn("-m", out)
