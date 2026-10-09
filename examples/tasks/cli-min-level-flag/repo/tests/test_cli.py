import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from levelcount import count_levels, level_of, main

SAMPLE = """\
2024-05-01T10:00:00 INFO started
2024-05-01T10:00:01 debug cache warm
2024-05-01T10:00:02 [warn] slow request
2024-05-01T10:00:03 ERROR boom
2024-05-01T10:00:04 INFO done
not a log line
"""


class ParseTests(unittest.TestCase):
    def test_level_of(self):
        self.assertEqual(level_of("t INFO x"), "INFO")
        self.assertEqual(level_of("t [warn] x"), "WARNING")
        self.assertIsNone(level_of("garbage"))

    def test_count(self):
        counts = count_levels(SAMPLE.splitlines())
        self.assertEqual(counts["INFO"], 2)
        self.assertEqual(counts["WARNING"], 1)


class CliTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".log")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(SAMPLE)

    def tearDown(self):
        os.remove(self.path)

    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(list(argv))
        return code, out.getvalue()

    def test_table(self):
        code, out = self.run_cli(self.path)
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-1].split(), ["TOTAL", "5"])

    def test_json(self):
        code, out = self.run_cli("--json", self.path)
        self.assertEqual(json.loads(out), {"DEBUG": 1, "INFO": 2, "WARNING": 1, "ERROR": 1})


if __name__ == "__main__":
    unittest.main()
