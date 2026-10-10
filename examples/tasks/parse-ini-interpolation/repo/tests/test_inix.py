import unittest

from inix import Config, MissingError, ParseError, dumps, parse

SAMPLE = """\
# deploy settings
[db]
host = localhost
port = 5432
debug = Yes

[web]
title = My App
motd = line one
    line two
; trailing comment
workers = 4
"""


class ParserTests(unittest.TestCase):
    def test_parse(self):
        data = parse(SAMPLE)
        self.assertEqual(list(data), ["db", "web"])
        self.assertEqual(data["db"]["port"], "5432")
        self.assertEqual(data["web"]["motd"], "line one\nline two")

    def test_errors(self):
        with self.assertRaises(ParseError) as ctx:
            parse("[a]\nnot a pair\n")
        self.assertEqual(ctx.exception.line, 2)
        with self.assertRaises(ParseError):
            parse("k = v\n")
        with self.assertRaises(ParseError):
            parse("[]\n")

    def test_reopened_section_and_duplicate_key(self):
        data = parse("[a]\nx = 1\n[b]\ny = 2\n[a]\nx = 3\nz = 4\n")
        self.assertEqual(data["a"], {"x": "3", "z": "4"})


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config.from_string(SAMPLE)

    def test_get(self):
        self.assertEqual(self.cfg.get("db", "host"), "localhost")
        self.assertEqual(self.cfg.get("db", "nope", fallback="x"), "x")
        with self.assertRaises(MissingError):
            self.cfg.get("db", "nope")

    def test_typed(self):
        self.assertEqual(self.cfg.getint("db", "port"), 5432)
        self.assertIs(self.cfg.getbool("db", "debug"), True)
        self.assertEqual(self.cfg.getfloat("web", "workers"), 4.0)
        self.assertEqual(self.cfg.getint("web", "missing", fallback=7), 7)

    def test_items(self):
        self.assertEqual(self.cfg.items("db")["host"], "localhost")


class WriterTests(unittest.TestCase):
    def test_roundtrip(self):
        cfg = Config.from_string(SAMPLE)
        again = Config.from_string(dumps(cfg))
        self.assertEqual(again._data, cfg._data)

    def test_format(self):
        cfg = Config({"a": {"x": "1", "y": "p\nq"}, "b": {}})
        self.assertEqual(dumps(cfg), "[a]\nx = 1\ny = p\n    q\n\n[b]\n")


if __name__ == "__main__":
    unittest.main()
