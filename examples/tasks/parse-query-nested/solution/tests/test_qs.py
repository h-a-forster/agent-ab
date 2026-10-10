import unittest

from qs import encode, parse


class ParseTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(parse("a=1&b=2"), {"a": "1", "b": "2"})
        self.assertEqual(parse("?a=1"), {"a": "1"})

    def test_repeated(self):
        self.assertEqual(parse("a=1&a=2&a=3"), {"a": ["1", "2", "3"]})

    def test_decoding(self):
        self.assertEqual(parse("q=a%20b+c"), {"q": "a b c"})
        self.assertEqual(parse("k%3D=v%26"), {"k=": "v&"})

    def test_empty_parts(self):
        self.assertEqual(parse("a=1&&b&c=&=x"), {"a": "1", "b": "", "c": ""})
        self.assertEqual(parse(""), {})

    def test_value_with_equals(self):
        self.assertEqual(parse("a=b=c"), {"a": "b=c"})


class EncodeTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(encode({"a": "1", "b": ["x y", "z"]}), "a=1&b[]=x%20y&b[]=z")

    def test_reserved(self):
        self.assertEqual(encode({"q": "a&b=c"}), "q=a%26b%3Dc")


if __name__ == "__main__":
    unittest.main()
