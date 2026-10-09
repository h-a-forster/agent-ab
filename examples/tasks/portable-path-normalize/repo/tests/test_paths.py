import unittest

from archpath import UnsafePathError, is_safe, normalize, split_parts


class NormalizeTests(unittest.TestCase):
    def test_root_forms(self):
        self.assertEqual(normalize(""), "")
        self.assertEqual(normalize("."), "")
        self.assertEqual(normalize("a/.."), "")

    def test_single_name(self):
        self.assertEqual(normalize("readme.txt"), "readme.txt")

    def test_escape_rejected(self):
        with self.assertRaises(UnsafePathError):
            normalize("../x")
        self.assertFalse(is_safe(".."))

    def test_nul_rejected(self):
        self.assertFalse(is_safe("a\x00b"))

    def test_split_root(self):
        self.assertEqual(split_parts("."), [])
        self.assertEqual(split_parts("file"), ["file"])


if __name__ == "__main__":
    unittest.main()
