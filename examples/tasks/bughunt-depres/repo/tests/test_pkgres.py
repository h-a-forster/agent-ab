import unittest

from pkgres import (CycleError, LockfileError, PackageIndex, ResolutionError, SpecError, Version, VersionError,
                    dump, install_order, load, max_satisfying, parse_range, parse_requirement, resolve, satisfies)


def idx(data):
    return PackageIndex.from_dict(data)


class VersionTests(unittest.TestCase):
    def test_parse_and_str(self):
        v = Version.parse("v1.2.3-beta.1+b5")
        self.assertEqual((v.major, v.minor, v.patch, v.pre[0], v.build), (1, 2, 3, "beta", ("b5",)))
        self.assertEqual(str(v), "1.2.3-beta.1+b5")

    def test_errors(self):
        for bad in ("1.2", "1.2.3.4", "a.b.c", "01.2.3", ""):
            with self.assertRaises(VersionError):
                Version.parse(bad)

    def test_order(self):
        self.assertTrue(Version.parse("1.2.3") < Version.parse("1.10.0"))
        self.assertTrue(Version.parse("1.0.0-alpha") < Version.parse("1.0.0"))
        self.assertTrue(Version.parse("1.0.0-alpha") < Version.parse("1.0.0-beta"))
        self.assertEqual(Version.parse("1.0.0+a"), Version.parse("1.0.0+b"))


class RangeTests(unittest.TestCase):
    def check(self, rng, yes, no):
        r = parse_range(rng)
        for v in yes:
            self.assertTrue(r.matches(v), "%s should match %s" % (rng, v))
        for v in no:
            self.assertFalse(r.matches(v), "%s should not match %s" % (rng, v))

    def test_comparators(self):
        self.check(">=1.0.0 <2.0.0", ["1.0.0", "1.9.9"], ["0.9.9", "2.0.0"])
        self.check(">1.0.0", ["1.0.1"], ["1.0.0"])
        self.check("=1.2.3", ["1.2.3"], ["1.2.4"])
        self.check("1.2.3", ["1.2.3"], ["1.2.4"])

    def test_caret_tilde(self):
        self.check("^1.2.3", ["1.2.3", "1.9.0"], ["1.2.2", "2.0.0"])
        self.check("~1.2.3", ["1.2.3", "1.2.9"], ["1.3.0"])
        self.check("~1.2", ["1.2.0", "1.2.7"], ["1.3.0"])

    def test_x_ranges(self):
        self.check("1.2.x", ["1.2.0", "1.2.9"], ["1.3.0"])
        self.check("*", ["0.0.1", "99.0.0"], [])

    def test_hyphen_and_union(self):
        self.check("1.2.3 - 2.3.4", ["1.2.3", "2.3.4"], ["1.2.2", "2.3.5"])
        self.check("1.0.0 || >=3.0.0 <4.0.0", ["1.0.0", "3.5.0"], ["2.0.0", "4.0.0"])

    def test_errors(self):
        for bad in ("abc", "1.2.3.4", "^"):
            with self.assertRaises(SpecError):
                parse_range(bad)

    def test_max_satisfying(self):
        self.assertEqual(max_satisfying(["1.0.0", "1.5.0", "2.0.0"], "^1.0.0"), Version.parse("1.5.0"))
        self.assertIsNone(max_satisfying(["1.0.0"], ">=2.0.0"))
        self.assertTrue(satisfies("1.5.0", "^1.0.0"))


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.index = idx({
            "app": {"1.0.0": {"left": "^1.2.0", "right": "~2.0"}},
            "left": {"1.2.0": {}, "1.3.1": {}, "2.0.0": {}},
            "right": {"2.0.4": {}, "2.0.1": {}, "2.1.0": {}},
        })

    def test_highest_matching(self):
        res = resolve(self.index, {"app": "*"})
        self.assertEqual(res, {"app": "1.0.0", "left": "1.3.1", "right": "2.0.4"})

    def test_unsolvable(self):
        with self.assertRaises(ResolutionError):
            resolve(self.index, {"app": "*", "left": "^2.0.0"})

    def test_install_order(self):
        res = resolve(self.index, {"app": "*"})
        self.assertEqual(install_order(res, self.index), ["left", "right", "app"])

    def test_cycle(self):
        index = idx({"a": {"1.0.0": {"b": "*"}}, "b": {"1.0.0": {"a": "*"}}})
        res = resolve(index, {"a": "*"})
        with self.assertRaises(CycleError):
            install_order(res, index)

    def test_lockfile_roundtrip(self):
        res = resolve(self.index, {"app": "*"})
        text = dump(res)
        self.assertEqual(text.splitlines()[1:], ["app@1.0.0", "left@1.3.1", "right@2.0.4"])
        self.assertEqual(load(text), res)
        with self.assertRaises(LockfileError):
            load("justaname\n")

    def test_requirements(self):
        name, rng = parse_requirement("left-pad@^1.2")
        self.assertEqual(name, "left-pad")
        self.assertTrue(rng.matches("1.3.0"))
        self.assertEqual(parse_requirement("plain")[0], "plain")


if __name__ == "__main__":
    unittest.main()
