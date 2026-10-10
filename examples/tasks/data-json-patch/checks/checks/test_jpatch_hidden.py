import copy
import random
import unittest

from jpatch import PatchError, PointerError, apply_patch, diff, json_equal, parse_pointer, resolve


def ap(doc, *ops):
    return apply_patch(doc, list(ops))


def fails_at(doc, ops):
    with unittest.TestCase().assertRaises(PatchError) as ctx:
        apply_patch(doc, ops)
    return ctx.exception.index


class Pointers(unittest.TestCase):
    def test_single_pass_unescape(self):
        self.assertEqual(parse_pointer("/~01"), ["~1"])
        self.assertEqual(parse_pointer("/~10"), ["/0"])
        self.assertEqual(parse_pointer("/a~1b~0c"), ["a/b~c"])
        self.assertEqual(parse_pointer("//"), ["", ""])

    def test_bad_escapes(self):
        for p in ("/~", "/a~", "/~2", "/a~x/b", "/~ "):
            with self.assertRaises(PointerError, msg=p):
                parse_pointer(p)

    def test_bad_pointers(self):
        for p in ("a", "a/b", " /a", None, 5):
            with self.assertRaises(PointerError, msg=repr(p)):
                parse_pointer(p)
            with self.assertRaises(PointerError, msg=repr(p)):
                resolve({}, p, default=1)

    def test_resolve_strict_indexes(self):
        doc = {"l": [10, 20, 30]}
        self.assertEqual(resolve(doc, "/l/0"), 10)
        self.assertEqual(resolve(doc, "/l/2"), 30)
        for p in ("/l/3", "/l/01", "/l/+1", "/l/-1", "/l/-", "/l/ 1", "/l/1.0", "/l/00", "/l/x"):
            self.assertEqual(resolve(doc, p, default="D"), "D", p)
            with self.assertRaises(PointerError, msg=p):
                resolve(doc, p)

    def test_resolve_misc(self):
        doc = {"": 1, "a/b": 2, "m~n": 3, "0": "zero", "n": None}
        self.assertEqual(resolve(doc, "/"), 1)
        self.assertEqual(resolve(doc, "/a~1b"), 2)
        self.assertEqual(resolve(doc, "/m~0n"), 3)
        self.assertEqual(resolve(doc, "/0"), "zero")
        self.assertIsNone(resolve(doc, "/n"))
        self.assertEqual(resolve(doc, "/n/x", default=7), 7)
        self.assertIs(resolve(doc, ""), doc)
        self.assertEqual(resolve({"s": "abc"}, "/s/0", default=None), None)


class Equality(unittest.TestCase):
    def test_bool_vs_number(self):
        self.assertFalse(json_equal(True, 1))
        self.assertFalse(json_equal(0, False))
        self.assertFalse(json_equal([True], [1]))
        self.assertFalse(json_equal({"a": [0]}, {"a": [False]}))
        self.assertTrue(json_equal(True, True))
        self.assertTrue(json_equal(False, False))

    def test_numbers_and_others(self):
        self.assertTrue(json_equal(1, 1.0))
        self.assertTrue(json_equal([1, {"a": 2.0}], [1.0, {"a": 2}]))
        self.assertFalse(json_equal(1, "1"))
        self.assertFalse(json_equal(None, 0))
        self.assertFalse(json_equal(None, False))
        self.assertTrue(json_equal(None, None))
        self.assertFalse(json_equal([], {}))
        self.assertFalse(json_equal({"a": 1}, {"a": 1, "b": 2}))
        self.assertFalse(json_equal([1, 2], [1, 2, 3]))
        self.assertTrue(json_equal({"a": 1, "b": 2}, {"b": 2, "a": 1}))
        self.assertFalse(json_equal({"a": 1}, {"b": 1}))


class Operations(unittest.TestCase):
    def test_rfc_examples(self):
        self.assertEqual(ap({"foo": "bar"}, {"op": "add", "path": "/baz", "value": "qux"}),
                         {"foo": "bar", "baz": "qux"})
        self.assertEqual(ap({"foo": ["bar", "baz"]}, {"op": "add", "path": "/foo/1", "value": "qux"}),
                         {"foo": ["bar", "qux", "baz"]})
        self.assertEqual(ap({"foo": "bar"}, {"op": "replace", "path": "/foo", "value": "x"}), {"foo": "x"})
        self.assertEqual(ap({"foo": [1, 2, 3]}, {"op": "remove", "path": "/foo/1"}), {"foo": [1, 3]})
        self.assertEqual(ap({"foo": {"bar": "baz", "waldo": "fred"}, "qux": {"corge": "grault"}},
                            {"op": "move", "from": "/foo/waldo", "path": "/qux/thud"}),
                         {"foo": {"bar": "baz"}, "qux": {"corge": "grault", "thud": "fred"}})
        self.assertEqual(ap({"foo": ["all", "grass", "cows", "eat"]}, {"op": "move", "from": "/foo/1", "path": "/foo/3"}),
                         {"foo": ["all", "cows", "eat", "grass"]})
        self.assertEqual(ap({"foo": "bar"}, {"op": "copy", "from": "/foo", "path": "/baz"}),
                         {"foo": "bar", "baz": "bar"})

    def test_add_root_and_dash(self):
        self.assertEqual(ap({"a": 1}, {"op": "add", "path": "", "value": [1]}), [1])
        self.assertEqual(ap([1, 2], {"op": "add", "path": "/-", "value": 3}, {"op": "add", "path": "/2", "value": 9}),
                         [1, 2, 9, 3])
        self.assertEqual(ap({"l": []}, {"op": "add", "path": "/l/-", "value": {"a": 1}}), {"l": [{"a": 1}]})
        self.assertEqual(ap([], {"op": "add", "path": "/0", "value": 1}), [1])

    def test_add_overwrites_key(self):
        self.assertEqual(ap({"a": 1}, {"op": "add", "path": "/a", "value": 2}), {"a": 2})

    def test_add_errors(self):
        base = {"l": [1, 2], "s": "x", "n": 5}
        for path in ("/l/3", "/l/01", "/l/-1", "/l/x", "/missing/a", "/s/a", "/n/0", "/l/1/a"):
            self.assertEqual(fails_at(base, [{"op": "add", "path": path, "value": 0}]), 0, path)
        self.assertEqual(fails_at(base, [{"op": "add", "path": "/ok", "value": 1},
                                         {"op": "add", "path": "/l/9", "value": 0}]), 1)

    def test_remove_errors(self):
        base = {"l": [1, 2], "d": {}}
        for path in ("", "/nope", "/l/2", "/l/-", "/l/01", "/d/x", "/nope/x"):
            self.assertEqual(fails_at(base, [{"op": "remove", "path": path}]), 0, path)

    def test_replace(self):
        self.assertEqual(ap({"l": [1, 2]}, {"op": "replace", "path": "/l/1", "value": None}), {"l": [1, None]})
        self.assertEqual(ap({"l": [1]}, {"op": "replace", "path": "", "value": 5}), 5)
        for path in ("/nope", "/l/2", "/l/-", "/l/1/x"):
            self.assertEqual(fails_at({"l": [1, 2]}, [{"op": "replace", "path": path, "value": 0}]), 0, path)

    def test_move(self):
        self.assertEqual(ap({"a": [1, 2, 3]}, {"op": "move", "from": "/a/0", "path": "/a/2"}), {"a": [2, 3, 1]})
        self.assertEqual(ap({"a": [1, 2, 3]}, {"op": "move", "from": "/a/2", "path": "/a/0"}), {"a": [3, 1, 2]})
        self.assertEqual(ap({"a": [1, 2, 3]}, {"op": "move", "from": "/a/0", "path": "/a/-"}), {"a": [2, 3, 1]})
        self.assertEqual(ap({"a": 1}, {"op": "move", "from": "/a", "path": "/b"}), {"b": 1})
        self.assertEqual(ap({"a": 1, "b": 2}, {"op": "move", "from": "/a", "path": "/b"}), {"b": 1})

    def test_move_edge_cases(self):
        self.assertEqual(ap({"a": {"b": 1}}, {"op": "move", "from": "/a", "path": "/a"}), {"a": {"b": 1}})
        self.assertEqual(fails_at({"a": 1}, [{"op": "move", "from": "/zz", "path": "/zz"}]), 0)
        self.assertEqual(fails_at({"a": {"b": 1}}, [{"op": "move", "from": "/a", "path": "/a/b"}]), 0)
        self.assertEqual(fails_at({"a": {"b": 1}}, [{"op": "move", "from": "/a", "path": "/a/c/d"}]), 0)
        self.assertEqual(fails_at({"a": 1}, [{"op": "move", "from": "", "path": "/x"}]), 0)
        self.assertEqual(ap({"a": 1}, {"op": "move", "from": "", "path": ""}), {"a": 1})
        self.assertEqual(ap({"ab": 1}, {"op": "move", "from": "/ab", "path": "/abc"}), {"abc": 1})
        self.assertEqual(fails_at({"a": 1}, [{"op": "move", "from": "/a", "path": "/x/y"}]), 0)

    def test_copy_is_independent(self):
        doc = {"a": {"b": [1]}}
        out = ap(doc, {"op": "copy", "from": "/a", "path": "/c"})
        out["c"]["b"].append(2)
        self.assertEqual(out["a"], {"b": [1]})
        self.assertEqual(ap([1, 2], {"op": "copy", "from": "/0", "path": "/-"}), [1, 2, 1])
        self.assertEqual(fails_at({"a": 1}, [{"op": "copy", "from": "/zz", "path": "/y"}]), 0)

    def test_test_op(self):
        doc = {"a": [1, {"b": None}], "t": True}
        ok = [{"op": "test", "path": "/a/1/b", "value": None}, {"op": "test", "path": "/a", "value": [1.0, {"b": None}]},
              {"op": "test", "path": "/t", "value": True}, {"op": "test", "path": "", "value": doc}]
        self.assertEqual(apply_patch(doc, ok), doc)
        self.assertEqual(fails_at(doc, [{"op": "test", "path": "/t", "value": 1}]), 0)
        self.assertEqual(fails_at(doc, [{"op": "test", "path": "/a/0", "value": True}]), 0)
        self.assertEqual(fails_at(doc, [{"op": "test", "path": "/nope", "value": None}]), 0)
        self.assertEqual(fails_at(doc, [{"op": "test", "path": "/a", "value": [1]}]), 0)

    def test_test_guards_following_ops(self):
        self.assertEqual(fails_at({"v": 1}, [{"op": "test", "path": "/v", "value": 1},
                                             {"op": "test", "path": "/v", "value": 2},
                                             {"op": "remove", "path": "/v"}]), 1)


class Validation(unittest.TestCase):
    def test_malformed_ops(self):
        cases = [
            {"op": "add", "path": "/a"},
            {"op": "replace", "path": "/a"},
            {"op": "test", "path": "/a"},
            {"op": "move", "path": "/a"},
            {"op": "copy", "path": "/a"},
            {"op": "move", "from": 1, "path": "/a"},
            {"op": "add", "value": 1},
            {"op": "add", "path": 5, "value": 1},
            {"op": "add", "path": "a", "value": 1},
            {"op": "add", "path": "/~", "value": 1},
            {"path": "/a", "value": 1},
            {"op": "nope", "path": "/a"},
            {"op": None, "path": "/a"},
            "add",
            None,
            ["add"],
        ]
        for op in cases:
            self.assertEqual(fails_at({"x": 1}, [{"op": "test", "path": "/x", "value": 1}, op]), 1, op)

    def test_null_value_is_present(self):
        self.assertEqual(ap({}, {"op": "add", "path": "/a", "value": None}), {"a": None})

    def test_not_a_list(self):
        for bad in ({"op": "add", "path": "/a", "value": 1}, "x", None, 5):
            with self.assertRaises(PatchError) as ctx:
                apply_patch({}, bad)
            self.assertIsNone(ctx.exception.index)

    def test_error_is_value_error_with_index_in_message(self):
        with self.assertRaises(ValueError) as ctx:
            apply_patch({}, [{"op": "remove", "path": "/x"}])
        self.assertIn("0", str(ctx.exception))

    def test_empty_patch(self):
        doc = {"a": [1]}
        out = apply_patch(doc, [])
        self.assertEqual(out, doc)


class Isolation(unittest.TestCase):
    def test_input_not_mutated(self):
        doc = {"a": [1, 2, {"b": 3}], "c": {"d": 4}}
        snapshot = copy.deepcopy(doc)
        ops = [
            {"op": "add", "path": "/a/0", "value": 0},
            {"op": "remove", "path": "/c/d"},
            {"op": "replace", "path": "/a/3/b", "value": 9},
            {"op": "move", "from": "/a", "path": "/z"},
            {"op": "copy", "from": "/c", "path": "/c2"},
        ]
        ops_snapshot = copy.deepcopy(ops)
        apply_patch(doc, ops)
        self.assertEqual(doc, snapshot)
        self.assertEqual(ops, ops_snapshot)

    def test_failed_patch_does_not_modify_input(self):
        doc = {"a": [1, 2]}
        with self.assertRaises(PatchError):
            apply_patch(doc, [{"op": "remove", "path": "/a/0"}, {"op": "remove", "path": "/nope"}])
        self.assertEqual(doc, {"a": [1, 2]})

    def test_no_aliasing_with_ops_values(self):
        value = {"k": [1]}
        ops = [{"op": "add", "path": "/x", "value": value}, {"op": "replace", "path": "/y", "value": value},
               {"op": "copy", "from": "/x", "path": "/z"}]
        out = apply_patch({"y": 0}, ops)
        out["x"]["k"].append(2)
        out["y"]["k"].append(3)
        out["z"]["k"].append(4)
        self.assertEqual(value, {"k": [1]})
        self.assertEqual(out["x"], {"k": [1, 2]})
        self.assertEqual(out["z"], {"k": [1, 4]})
        root = apply_patch({}, [{"op": "add", "path": "", "value": value}])
        root["k"].append(5)
        self.assertEqual(value, {"k": [1]})
        root = apply_patch({}, [{"op": "replace", "path": "", "value": value}])
        root["k"].append(5)
        self.assertEqual(value, {"k": [1]})

    def test_result_independent_of_input(self):
        doc = {"a": {"b": [1]}}
        out = apply_patch(doc, [])
        out["a"]["b"].append(2)
        self.assertEqual(doc, {"a": {"b": [1]}})


class Diff(unittest.TestCase):
    def test_equal_is_empty(self):
        self.assertEqual(diff({"a": [1, {"b": 2}]}, {"a": [1.0, {"b": 2}]}), [])
        self.assertEqual(diff([], []), [])

    def test_bool_vs_int_differs(self):
        self.assertEqual(diff({"a": True}, {"a": 1}), [{"op": "replace", "path": "/a", "value": 1}])
        self.assertEqual(diff([0], [False]), [{"op": "replace", "path": "/0", "value": False}])

    def test_object_order_and_ops(self):
        a = {"x": 1, "y": 2, "z": 3}
        b = {"z": 3, "w": 0, "x": 5}
        self.assertEqual(diff(a, b), [
            {"op": "remove", "path": "/y"},
            {"op": "add", "path": "/w", "value": 0},
            {"op": "replace", "path": "/x", "value": 5},
        ])

    def test_escaped_keys(self):
        a = {"a/b": 1, "m~n": 2, "": 3}
        b = {"a/b": 2, "m~n": 3, "": 4, "x/~y": 5}
        ops = diff(a, b)
        self.assertEqual(ops, [
            {"op": "replace", "path": "/a~1b", "value": 2},
            {"op": "replace", "path": "/m~0n", "value": 3},
            {"op": "replace", "path": "/", "value": 4},
            {"op": "add", "path": "/x~1~0y", "value": 5},
        ])
        self.assertEqual(apply_patch(a, ops), b)
        self.assertEqual(diff({"~1": 1}, {}), [{"op": "remove", "path": "/~01"}])

    def test_arrays_elementwise(self):
        self.assertEqual(diff([1, 2, 3], [1, 5, 3]), [{"op": "replace", "path": "/1", "value": 5}])
        self.assertEqual(diff([1], [1, 2, 3]), [{"op": "add", "path": "/1", "value": 2},
                                                {"op": "add", "path": "/2", "value": 3}])
        self.assertEqual(diff([1, 2, 3, 4], [1]), [{"op": "remove", "path": "/3"}, {"op": "remove", "path": "/2"},
                                                   {"op": "remove", "path": "/1"}])
        self.assertEqual(diff({"l": [{"a": 1}, 2]}, {"l": [{"a": 2}, 2, 3]}),
                         [{"op": "replace", "path": "/l/0/a", "value": 2}, {"op": "add", "path": "/l/2", "value": 3}])

    def test_type_changes_and_root(self):
        self.assertEqual(diff({"a": 1}, [1]), [{"op": "replace", "path": "", "value": [1]}])
        self.assertEqual(diff(1, 2), [{"op": "replace", "path": "", "value": 2}])
        self.assertEqual(diff({"a": {"b": 1}}, {"a": [1]}), [{"op": "replace", "path": "/a", "value": [1]}])
        self.assertEqual(diff({"a": None}, {"a": 0}), [{"op": "replace", "path": "/a", "value": 0}])
        self.assertEqual(diff([[1]], [{"x": 1}]), [{"op": "replace", "path": "/0", "value": {"x": 1}}])

    def test_values_are_copies(self):
        b = {"n": {"k": [1]}}
        ops = diff({}, b)
        ops[0]["value"]["k"].append(2)
        self.assertEqual(b, {"n": {"k": [1]}})
        ops = diff([], [[1]])
        ops[0]["value"].append(2)
        ops = diff(1, b)
        ops[0]["value"]["n"]["k"].append(9)
        self.assertEqual(b, {"n": {"k": [1]}})

    def test_random_roundtrip(self):
        rng = random.Random(99)
        keys = ["a", "b", "a/b", "~", "", "x~1", "0"]

        def gen(depth):
            r = rng.random()
            if depth == 0 or r < 0.3:
                return rng.choice([None, True, False, 0, 1, 2.5, "s", "", 1.0])
            if r < 0.65:
                return {k: gen(depth - 1) for k in rng.sample(keys, rng.randint(0, 4))}
            return [gen(depth - 1) for _ in range(rng.randint(0, 4))]

        for _ in range(500):
            a, b = gen(3), gen(3)
            a0, b0 = copy.deepcopy(a), copy.deepcopy(b)
            ops = diff(a, b)
            out = apply_patch(a, ops)
            self.assertTrue(json_equal(out, b), (a, b, ops, out))
            self.assertEqual((a, b), (a0, b0))
            if json_equal(a, b):
                self.assertEqual(ops, [])
            for op in ops:
                self.assertIn(op["op"], ("add", "remove", "replace"))


if __name__ == "__main__":
    unittest.main()
