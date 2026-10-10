import random
import unittest

from qs import ParseError, encode, parse
from qs.codec import quote, unquote_plus


class Codec(unittest.TestCase):
    def test_plus_before_percent(self):
        self.assertEqual(unquote_plus("a+b%2Bc%20d"), "a b+c d")
        self.assertEqual(unquote_plus("%2B%2b"), "++")

    def test_utf8_sequences(self):
        self.assertEqual(unquote_plus("%C3%A9"), "é")
        self.assertEqual(unquote_plus("caf%C3%A9+%E2%82%AC"), "café €")
        self.assertEqual(unquote_plus("%F0%9F%98%80"), "\U0001F600")
        self.assertEqual(unquote_plus("a%C3%A9%C3%A8b"), "aéèb")

    def test_invalid_utf8(self):
        self.assertEqual(unquote_plus("%FF"), "�")
        self.assertEqual(unquote_plus("a%E2%82b"), "a�b")

    def test_malformed_percent_literal(self):
        for raw in ("100%", "%zz", "%4", "a%", "%%41", "%G1"):
            want = {"%%41": "%A"}.get(raw, raw)
            self.assertEqual(unquote_plus(raw), want, raw)

    def test_quote(self):
        self.assertEqual(quote("aZ09-._~"), "aZ09-._~")
        self.assertEqual(quote("é €"), "%C3%A9%20%E2%82%AC")
        self.assertEqual(quote("a b&c=d/e[f]+"), "a%20b%26c%3Dd%2Fe%5Bf%5D%2B")
        self.assertEqual(quote("\U0001F600"), "%F0%9F%98%80")
        self.assertEqual(quote(""), "")


class FlatParsing(unittest.TestCase):
    def test_flat_still_works(self):
        self.assertEqual(parse("a=1&b=2"), {"a": "1", "b": "2"})
        self.assertEqual(parse("?a=1&a=2&a=3"), {"a": ["1", "2", "3"]})
        self.assertEqual(parse("a=1&&b&c=&=x&"), {"a": "1", "b": "", "c": ""})
        self.assertEqual(parse("a=b=c"), {"a": "b=c"})
        self.assertEqual(parse("?"), {})

    def test_decoding_in_pairs(self):
        self.assertEqual(parse("q=caf%C3%A9+au+lait&p=1%2B1"), {"q": "café au lait", "p": "1+1"})
        self.assertEqual(parse("n%C3%A9=x"), {"né": "x"})
        self.assertEqual(parse("k=100%"), {"k": "100%"})

    def test_question_mark_only_leading(self):
        self.assertEqual(parse("?a=1?b"), {"a": "1?b"})
        self.assertEqual(parse("a?b=1"), {"a?b": "1"})


class Nested(unittest.TestCase):
    def test_simple_nesting(self):
        self.assertEqual(parse("user[name]=x&user[age]=3"), {"user": {"name": "x", "age": "3"}})

    def test_deep_nesting(self):
        self.assertEqual(parse("a[b][c][d]=1"), {"a": {"b": {"c": {"d": "1"}}}})
        self.assertEqual(parse("a[b][c]=1&a[b][d]=2&a[e]=3"), {"a": {"b": {"c": "1", "d": "2"}, "e": "3"}})

    def test_depth_limit(self):
        ok = "a" + "[x]" * 5 + "=1"
        bad = "a" + "[x]" * 6 + "=1"
        self.assertEqual(parse(ok)["a"]["x"]["x"]["x"]["x"]["x"], "1")
        with self.assertRaises(ParseError):
            parse(bad)
        self.assertEqual(parse(bad, max_depth=6)["a"]["x"]["x"]["x"]["x"]["x"]["x"], "1")
        with self.assertRaises(ParseError):
            parse("a[b][c]=1", max_depth=1)
        self.assertEqual(parse("a[b]=1", max_depth=1), {"a": {"b": "1"}})
        with self.assertRaises(ParseError):
            parse("a[b][]=1", max_depth=1)

    def test_empty_brackets_collect(self):
        self.assertEqual(parse("a[]=1"), {"a": ["1"]})
        self.assertEqual(parse("a[]=1&a[]=2&a[]=3"), {"a": ["1", "2", "3"]})
        self.assertEqual(parse("a[b][]=1&a[b][]=2"), {"a": {"b": ["1", "2"]}})
        self.assertEqual(parse("a[]="), {"a": [""]})
        self.assertEqual(parse("a[]"), {"a": [""]})

    def test_empty_brackets_must_be_last(self):
        for q in ("a[][b]=1", "a[][]=1", "a[][b][]=1", "a[b][][c]=1"):
            with self.assertRaises(ParseError, msg=q):
                parse(q)

    def test_numeric_segments_are_keys(self):
        self.assertEqual(parse("a[0]=x&a[1]=y"), {"a": {"0": "x", "1": "y"}})
        self.assertEqual(parse("a[1]=y&a[0]=x"), {"a": {"1": "y", "0": "x"}})

    def test_empty_name_segment_is_a_key(self):
        self.assertEqual(parse("a[ ]=1"), {"a": {" ": "1"}})
        self.assertEqual(parse("a[%20]=1"), {"a": {" ": "1"}})

    def test_repeated_keys_accumulate(self):
        self.assertEqual(parse("a=1&a[]=2"), {"a": ["1", "2"]})
        self.assertEqual(parse("a[]=1&a=2"), {"a": ["1", "2"]})
        self.assertEqual(parse("a[b]=1&a[b]=2&a[b]=3"), {"a": {"b": ["1", "2", "3"]}})
        self.assertEqual(parse("a[b]=1&a[b][]=2"), {"a": {"b": ["1", "2"]}})
        self.assertEqual(parse("a=1&a=2&a[]=3"), {"a": ["1", "2", "3"]})

    def test_conflicts(self):
        for q in ("a[b]=1&a=2", "a[b]=1&a[]=2", "a=1&a[b]=2", "a[]=1&a[b]=2", "a=1&a=2&a[b]=3",
                  "a[b]=1&a[b][c]=2", "a[b][c]=1&a[b]=2", "a[b][c]=1&a[b][]=2"):
            with self.assertRaises(ParseError, msg=q):
                parse(q)

    def test_key_order_is_first_appearance(self):
        self.assertEqual(list(parse("z=1&a[y]=2&m=3&a[x]=4&z=5")), ["z", "a", "m"])
        self.assertEqual(list(parse("z=1&a[y]=2&m=3&a[x]=4&z=5")["a"]), ["y", "x"])

    def test_values_decoded_and_strings(self):
        r = parse("a[b]=%C3%A9+x&c[]=1")
        self.assertEqual(r, {"a": {"b": "é x"}, "c": ["1"]})

    def test_segments_decoded_individually(self):
        self.assertEqual(parse("a%20b[c%2Fd]=1"), {"a b": {"c/d": "1"}})
        self.assertEqual(parse("%C3%A9[%C3%A8]=1"), {"é": {"è": "1"}})


class LiteralKeys(unittest.TestCase):
    def test_encoded_brackets_are_not_structure(self):
        self.assertEqual(parse("a%5Bb%5D=1"), {"a[b]": "1"})
        self.assertEqual(parse("a%5B%5D=1&a%5B%5D=2"), {"a[]": ["1", "2"]})

    def test_malformed_brackets_are_literal(self):
        self.assertEqual(parse("[a]=1"), {"[a]": "1"})
        self.assertEqual(parse("a[b=1"), {"a[b": "1"})
        self.assertEqual(parse("a[b]c=1"), {"a[b]c": "1"})
        self.assertEqual(parse("a]=1"), {"a]": "1"})
        self.assertEqual(parse("a[[b]]=1"), {"a[[b]]": "1"})
        self.assertEqual(parse("a[b]]=1"), {"a[b]]": "1"})
        self.assertEqual(parse("[]=1"), {"[]": "1"})

    def test_literal_keys_still_accumulate(self):
        self.assertEqual(parse("[a]=1&[a]=2"), {"[a]": ["1", "2"]})

    def test_literal_bracket_key_vs_nested_do_not_conflict(self):
        self.assertEqual(parse("a[b=1&a[c]=2"), {"a[b": "1", "a": {"c": "2"}})

    def test_literal_key_is_decoded(self):
        self.assertEqual(parse("[a]%20b=1"), {"[a] b": "1"})


class Encoding(unittest.TestCase):
    def test_flat(self):
        self.assertEqual(encode({"a": "1", "b": "x y"}), "a=1&b=x%20y")
        self.assertEqual(encode({}), "")

    def test_nested(self):
        self.assertEqual(encode({"u": {"name": "é", "tags": {"x": "1"}}}), "u[name]=%C3%A9&u[tags][x]=1")

    def test_lists(self):
        self.assertEqual(encode({"a": ["1", "2"], "b": ["x"]}), "a[]=1&a[]=2&b[]=x")
        self.assertEqual(encode({"a": {"b": ["1", "2"]}}), "a[b][]=1&a[b][]=2")
        self.assertEqual(encode({"t": ("p", "q")}), "t[]=p&t[]=q")

    def test_empty_containers_write_nothing(self):
        self.assertEqual(encode({"a": [], "b": {}, "c": "1", "d": {"e": []}}), "c=1")

    def test_scalars(self):
        self.assertEqual(encode({"a": True, "b": False, "c": 5, "d": 2.5, "e": None, "f": [1, True, None]}),
                         "a=true&b=false&c=5&d=2.5&e=&f[]=1&f[]=true&f[]=")

    def test_key_quoting(self):
        self.assertEqual(encode({"a b": {"c[d": "x"}}), "a%20b[c%5Bd]=x")
        self.assertEqual(encode({"k=": "v&"}), "k%3D=v%26")
        self.assertEqual(encode({"é": {"è": "ü"}}), "%C3%A9[%C3%A8]=%C3%BC")

    def test_errors(self):
        for bad, exc in [([("a", 1)], TypeError), ("a=1", TypeError), ({1: "x"}, TypeError), ({"": "x"}, ValueError),
                         ({"a": {"": "x"}}, ValueError), ({"a": [{"b": 1}]}, ValueError), ({"a": [[1]]}, ValueError),
                         ({"a": object()}, TypeError), ({"a": {1: "x"}}, TypeError), ({"a": [object()]}, TypeError)]:
            with self.assertRaises(exc, msg=repr(bad)):
                encode(bad)

    def test_old_flat_list_style_is_gone(self):
        self.assertNotEqual(encode({"b": ["x", "z"]}), "b=x&b=z")

    def test_roundtrip_fixed(self):
        data = {"a": "1", "u": {"n": "é & ü", "l": ["x y", "", "z"], "d": {"k": "v"}}, "e": [], "q[": "w]"}
        want = {"a": "1", "u": {"n": "é & ü", "l": ["x y", "", "z"], "d": {"k": "v"}}, "q[": "w]"}
        self.assertEqual(parse(encode(data)), want)

    def test_roundtrip_random(self):
        rng = random.Random(5)
        alphabet = ["a", "b", "[", "]", "&", "=", "+", "%", " ", "é", "/", "~", "x1"]

        def text():
            return "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 4)))

        def gen(depth):
            out = {}
            for _ in range(rng.randint(1, 3)):
                key = text()
                r = rng.random()
                if depth > 0 and r < 0.4:
                    out[key] = gen(depth - 1)
                elif r < 0.7:
                    out[key] = [text() if rng.random() < 0.8 else "" for _ in range(rng.randint(1, 3))]
                else:
                    out[key] = text()
            return out

        for _ in range(300):
            data = gen(2)
            self.assertEqual(parse(encode(data), max_depth=10), data, encode(data))


if __name__ == "__main__":
    unittest.main()
