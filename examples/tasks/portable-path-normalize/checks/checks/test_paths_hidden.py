import os
import unittest
from unittest import mock

from archpath import UnsafePathError, is_safe, normalize, split_parts

VALID = {
    "docs/a.txt": "docs/a.txt",
    "docs\\a.txt": "docs/a.txt",
    "docs\\sub/a.txt": "docs/sub/a.txt",
    "docs//a.txt": "docs/a.txt",
    "docs\\\\a.txt": "docs/a.txt",
    "docs/./a.txt": "docs/a.txt",
    "./docs/a.txt": "docs/a.txt",
    ".\\docs\\a.txt": "docs/a.txt",
    "docs/guide/../a.txt": "docs/a.txt",
    "docs\\guide\\..\\a.txt": "docs/a.txt",
    "a/b/c/../../d": "a/d",
    "docs/": "docs",
    "docs\\": "docs",
    "a/b/..": "a",
    "": "",
    ".": "",
    "./": "",
    ".\\": "",
    "a/..": "",
    "a\\..": "",
    "..config": "..config",
    "dir/..config/x": "dir/..config/x",
    "a..b": "a..b",
    "...": "...",
    "foo..": "foo..",
    "My Documents/Report FINAL.DOCX": "My Documents/Report FINAL.DOCX",
    "ab:c/d": "ab:c/d",
    "x/C:/y": "x/C:/y",
    "\u00fcber/na\u00efve.txt": "\u00fcber/na\u00efve.txt",
    " lead/trail ": " lead/trail ",
}

UNSAFE = [
    "..",
    "../x",
    "..\\x",
    "docs/../../x",
    "docs\\..\\..\\secret",
    "a/../../a/b",
    "a/b/../../..",
    "./..",
    "/etc/passwd",
    "\\windows\\system32",
    "/",
    "\\",
    "//server/share/x",
    "\\\\server\\share\\x",
    "C:",
    "C:\\temp\\x",
    "c:\\x",
    "C:foo",
    "d:/x",
    "Z:",
    "a\x00b",
    "docs/\x00",
]


class Portable(unittest.TestCase):
    def test_valid(self):
        for raw, expected in VALID.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize(raw), expected)
                self.assertTrue(is_safe(raw))
                self.assertEqual(split_parts(raw), expected.split("/") if expected else [])

    def test_unsafe(self):
        for raw in UNSAFE:
            with self.subTest(raw=raw):
                with self.assertRaises(UnsafePathError):
                    normalize(raw)
                with self.assertRaises(UnsafePathError):
                    split_parts(raw)
                self.assertFalse(is_safe(raw))

    def test_unsafe_error_is_value_error(self):
        with self.assertRaises(ValueError):
            normalize("../x")

    def test_idempotent(self):
        for raw, expected in VALID.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize(expected), expected)

    def test_independent_of_os_module(self):
        # The result must not depend on the host's path flavour.
        import ntpath
        import posixpath

        for flavour, sep in ((ntpath, "\\"), (posixpath, "/")):
            with mock.patch.object(os, "path", flavour), mock.patch.object(os, "sep", sep):
                for raw, expected in VALID.items():
                    with self.subTest(flavour=flavour.__name__, raw=raw):
                        self.assertEqual(normalize(raw), expected)
                for raw in UNSAFE:
                    with self.subTest(flavour=flavour.__name__, raw=raw):
                        self.assertFalse(is_safe(raw))

    def test_no_filesystem_access(self):
        with mock.patch("os.getcwd", side_effect=AssertionError("filesystem access")):
            self.assertEqual(normalize("a/./b/../c"), "a/c")
