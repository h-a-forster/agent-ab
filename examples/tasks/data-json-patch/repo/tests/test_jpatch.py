import unittest

from jpatch import PatchError, PointerError, apply_patch, diff, escape_token, parse_pointer, resolve


class PointerTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_pointer(""), [])
        self.assertEqual(parse_pointer("/a/b"), ["a", "b"])
        self.assertEqual(parse_pointer("/a~1b/m~0n"), ["a/b", "m~n"])
        self.assertEqual(parse_pointer("/"), [""])

    def test_bad_pointer(self):
        with self.assertRaises(PointerError):
            parse_pointer("a/b")

    def test_resolve(self):
        doc = {"a": [10, {"b": 2}], "": 0}
        self.assertEqual(resolve(doc, "/a/1/b"), 2)
        self.assertEqual(resolve(doc, "/"), 0)
        self.assertEqual(resolve(doc, "/zzz", default=None), None)
        with self.assertRaises(PointerError):
            resolve(doc, "/a/5")

    def test_escape(self):
        self.assertEqual(escape_token("a/b~c"), "a~1b~0c")


class PatchTests(unittest.TestCase):
    def test_add_remove_replace(self):
        doc = {"a": 1, "l": [1, 2, 3]}
        out = apply_patch(doc, [
            {"op": "add", "path": "/b", "value": {"x": 1}},
            {"op": "remove", "path": "/a"},
            {"op": "replace", "path": "/l/1", "value": 9},
            {"op": "add", "path": "/l/0", "value": 0},
        ])
        self.assertEqual(out, {"b": {"x": 1}, "l": [0, 1, 9, 3]})

    def test_root_replace(self):
        self.assertEqual(apply_patch({"a": 1}, [{"op": "replace", "path": "", "value": [1]}]), [1])

    def test_unsupported(self):
        with self.assertRaises(PatchError) as ctx:
            apply_patch({}, [{"op": "frobnicate", "path": ""}])
        self.assertEqual(ctx.exception.index, 0)


class DiffTests(unittest.TestCase):
    def test_roundtrip_dicts(self):
        a = {"a": 1, "b": {"c": 2, "d": 3}, "e": "x"}
        b = {"a": 1, "b": {"c": 5}, "f": [1]}
        self.assertEqual(apply_patch(a, diff(a, b)), b)

    def test_equal_is_empty(self):
        self.assertEqual(diff({"a": [1, 2]}, {"a": [1, 2]}), [])


if __name__ == "__main__":
    unittest.main()
