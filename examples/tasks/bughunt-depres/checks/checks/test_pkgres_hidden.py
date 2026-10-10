import unittest

from pkgres import (CycleError, LockfileError, PackageIndex, PkgresError, ResolutionError, SpecError, Version,
                    VersionError, dump, install_order, load, max_satisfying, min_satisfying, parse_range,
                    parse_requirement, parse_requirements, resolve, satisfies)
from pkgres.diff import Change, diff, format_changes, summarize
from pkgres.graph import dependency_map, dependents, depth, find_cycle
from pkgres.report import explain, format_resolution, install_plan, outdated, tree
from pkgres.version import sort_versions

V = Version.parse


def idx(data):
    return PackageIndex.from_dict(data)


class RangeCase(unittest.TestCase):
    def check(self, rng, yes=(), no=()):
        r = parse_range(rng)
        for v in yes:
            self.assertTrue(r.matches(v), "%s should match %s" % (rng, v))
        for v in no:
            self.assertFalse(r.matches(v), "%s should not match %s" % (rng, v))


class PrereleaseOrderSymptoms(unittest.TestCase):
    def test_numeric_identifiers(self):
        self.assertTrue(V("1.0.0-alpha.2") < V("1.0.0-alpha.10"))
        self.assertTrue(V("1.0.0-beta.2") < V("1.0.0-beta.11"))
        self.assertTrue(V("1.0.0-rc.9") < V("1.0.0-rc.10"))
        self.assertFalse(V("1.0.0-alpha.10") < V("1.0.0-alpha.2"))
        self.assertTrue(V("1.0.0-1.20") > V("1.0.0-1.3"))

    def test_semver_spec_chain(self):
        chain = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11",
                 "1.0.0-rc.1", "1.0.0"]
        shuffled = [chain[i] for i in (5, 2, 7, 0, 3, 6, 1, 4)]
        self.assertEqual([str(v) for v in sort_versions(shuffled)], chain)
        self.assertEqual([str(v) for v in sort_versions(chain, reverse=True)], chain[::-1])

    def test_numeric_before_alphanumeric(self):
        self.assertTrue(V("1.0.0-1") < V("1.0.0-alpha"))
        self.assertTrue(V("1.0.0-99") < V("1.0.0-a"))
        self.assertTrue(V("1.0.0-alpha") < V("1.0.0-alpha.0"))

    def test_max_and_min_satisfying(self):
        versions = ["1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-beta.3"]
        self.assertEqual(max_satisfying(versions, ">=1.0.0-beta.1"), V("1.0.0-beta.11"))
        self.assertEqual(min_satisfying(versions, ">=1.0.0-beta.1"), V("1.0.0-beta.2"))

    def test_range_comparisons_with_numeric_prerelease(self):
        r = parse_range(">=1.0.0-beta.2 <1.0.0")
        self.assertTrue(r.matches("1.0.0-beta.10"))
        self.assertFalse(r.matches("1.0.0-beta.1"))
        self.assertTrue(parse_range("<1.0.0-rc.10").matches("1.0.0-rc.9"))
        self.assertTrue(parse_range("<1.0.0-rc.10").matches("1.0.0-rc.2"))

    def test_resolver_prefers_numerically_highest_prerelease(self):
        index = idx({"a": {"1.0.0-rc.9": {}, "1.0.0-rc.10": {}, "1.0.0-rc.2": {}}})
        self.assertEqual(resolve(index, {"a": ">=1.0.0-rc.1"})["a"], V("1.0.0-rc.10"))
        self.assertEqual(index.versions("a"), [V("1.0.0-rc.10"), V("1.0.0-rc.9"), V("1.0.0-rc.2")])

    def test_diff_direction_uses_numeric_order(self):
        index = idx({"a": {"1.0.0-rc.9": {}, "1.0.0-rc.10": {}}})
        old = resolve(index, {"a": "1.0.0-rc.9"})
        new = resolve(index, {"a": "1.0.0-rc.10"})
        self.assertEqual([c.kind for c in diff(old, new)], ["upgraded"])
        self.assertEqual([c.kind for c in diff(new, old)], ["downgraded"])


class CaretSymptoms(RangeCase):
    def test_zero_minor(self):
        self.check("^0.2.3", yes=["0.2.3", "0.2.4", "0.2.99"], no=["0.2.2", "0.3.0", "1.0.0"])
        self.check("^0.12.0", yes=["0.12.0", "0.12.5"], no=["0.13.0", "0.11.9"])
        self.check("^0.10.1", yes=["0.10.1", "0.10.2"], no=["0.11.0"])

    def test_zero_zero(self):
        self.check("^0.0.3", yes=["0.0.3"], no=["0.0.4", "0.0.2", "0.1.0"])
        self.check("^0.0", yes=["0.0.0", "0.0.9"], no=["0.1.0"])

    def test_zero_major_only(self):
        self.check("^0", yes=["0.0.0", "0.9.9"], no=["1.0.0"])
        self.check("^0.x", yes=["0.0.0", "0.9.9"], no=["1.0.0"])
        self.check("^0.2", yes=["0.2.0", "0.2.8"], no=["0.3.0", "0.1.9"])

    def test_nonzero_major(self):
        self.check("^1.2.3", yes=["1.2.3", "1.99.0"], no=["1.2.2", "2.0.0"])
        self.check("^1.2", yes=["1.2.0", "1.9.9"], no=["1.1.9", "2.0.0"])
        self.check("^1", yes=["1.0.0", "1.9.9"], no=["2.0.0"])
        self.check("^1.x", yes=["1.0.0", "1.9.9"], no=["2.0.0"])

    def test_with_prerelease(self):
        self.check("^0.2.3-beta.1", yes=["0.2.3-beta.2", "0.2.3", "0.2.9"], no=["0.2.4-beta.1", "0.3.0", "0.2.3-alpha"])

    def test_resolver_uses_it(self):
        index = idx({"a": {"0.2.3": {}, "0.2.9": {}, "0.3.0": {}, "0.1.0": {}}})
        self.assertEqual(resolve(index, {"a": "^0.2.3"})["a"], V("0.2.9"))
        self.assertEqual(max_satisfying(["0.2.3", "0.2.9", "0.3.0"], "^0.2.3"), V("0.2.9"))
        self.assertTrue(satisfies("0.2.9", "^0.2.3"))

    def test_union_with_caret(self):
        self.check("^0.2.3 || ^1.0.0", yes=["0.2.5", "1.4.0"], no=["0.3.1", "2.0.0"])


class BareMajorSymptoms(RangeCase):
    def test_tilde_major(self):
        self.check("~1", yes=["1.0.0", "1.1.0", "1.9.9"], no=["2.0.0", "0.9.9"])
        self.check("~1.x", yes=["1.0.0", "1.9.9"], no=["2.0.0"])
        self.check("~0", yes=["0.0.0", "0.9.9"], no=["1.0.0"])

    def test_tilde_minor(self):
        self.check("~1.2", yes=["1.2.0", "1.2.9"], no=["1.3.0"])
        self.check("~1.2.3", yes=["1.2.3", "1.2.9"], no=["1.2.2", "1.3.0"])

    def test_bare_major(self):
        self.check("1", yes=["1.0.0", "1.5.0", "1.9.9"], no=["2.0.0", "0.9.0"])
        self.check("1.x", yes=["1.0.0", "1.9.9"], no=["2.0.0"])
        self.check("1.*", yes=["1.0.0", "1.9.9"], no=["2.0.0"])
        self.check("=1", yes=["1.3.0"], no=["2.0.0"])
        self.check("1.x.x", yes=["1.3.0"], no=["2.0.0"])

    def test_less_equal_and_greater(self):
        self.check("<=1", yes=["0.1.0", "1.0.0", "1.9.9"], no=["2.0.0"])
        self.check(">1", yes=["2.0.0", "3.1.0"], no=["1.9.9", "1.0.0"])
        self.check("<=1.2", yes=["1.2.9"], no=["1.3.0"])
        self.check(">1.2", yes=["1.3.0"], no=["1.2.9"])
        self.check("<=2", yes=["2.9.9"], no=["3.0.0"])

    def test_hyphen_with_partial_upper(self):
        self.check("1.2.3 - 2", yes=["1.2.3", "2.0.0", "2.9.9"], no=["3.0.0", "1.2.2"])
        self.check("1.2.3 - 2.3", yes=["2.3.9"], no=["2.4.0"])
        self.check("1.2.3 - 2.3.4", yes=["2.3.4"], no=["2.3.5"])
        self.check("1 - 2", yes=["1.0.0", "2.9.9"], no=["3.0.0", "0.9.9"])

    def test_combined_in_resolution(self):
        index = idx({"a": {"1.0.0": {}, "1.4.0": {}, "2.0.0": {}}})
        for spec in ("~1", "1", "1.x", "<=1", "0.5 - 1"):
            self.assertEqual(resolve(index, {"a": spec})["a"], V("1.4.0"), spec)

    def test_caret_all_zero_single(self):
        self.check("^0", yes=["0.4.0"], no=["1.0.0"])


class BacktrackSymptoms(unittest.TestCase):
    def test_conflicting_branch_is_forgotten(self):
        index = idx({
            "A": {"1.0.0": {"C": "^1.0.0"}, "2.0.0": {"C": "^2.0.0"}},
            "B": {"1.0.0": {"C": "^1.0.0"}},
            "C": {"1.0.0": {}, "1.5.0": {}, "2.0.0": {}},
        })
        res = resolve(index, {"A": "*", "B": "*"})
        self.assertEqual(res, {"A": "1.0.0", "B": "1.0.0", "C": "1.5.0"})

    def test_dead_end_deeper(self):
        index = idx({
            "X": {"2.0.0": {"Y": "^2.0.0"}, "1.0.0": {"Y": "^1.0.0"}},
            "Y": {"2.0.0": {"Z": "^9.0.0"}, "1.0.0": {}},
            "Z": {"1.0.0": {}},
        })
        self.assertEqual(resolve(index, {"X": "*"}), {"X": "1.0.0", "Y": "1.0.0"})

    def test_multiple_abandoned_branches(self):
        index = idx({
            "app": {"1.0.0": {"lib": "*", "tool": "*"}},
            "lib": {"3.0.0": {"core": "^3.0.0"}, "2.0.0": {"core": "^2.0.0"}, "1.0.0": {"core": "^1.0.0"}},
            "tool": {"1.0.0": {"core": "<2.0.0"}},
            "core": {"3.1.0": {}, "2.2.0": {}, "1.7.0": {}, "1.1.0": {}},
        })
        res = resolve(index, {"app": "*"})
        self.assertEqual(res, {"app": "1.0.0", "lib": "1.0.0", "tool": "1.0.0", "core": "1.7.0"})

    def test_failed_compatibility_check_then_alternative(self):
        index = idx({
            "a": {"1.0.0": {}},
            "b": {"2.0.0": {"a": "^2.0.0"}, "1.0.0": {"a": "^1.0.0"}},
        })
        self.assertEqual(resolve(index, {"a": "*", "b": "*"}), {"a": "1.0.0", "b": "1.0.0"})

    def test_real_conflicts_still_fail(self):
        index = idx({
            "A": {"1.0.0": {"C": "^1.0.0"}},
            "B": {"1.0.0": {"C": "^2.0.0"}},
            "C": {"1.0.0": {}, "2.0.0": {}},
        })
        with self.assertRaises(ResolutionError) as cm:
            resolve(index, {"A": "*", "B": "*"})
        self.assertIsNotNone(cm.exception.name)

    def test_repeated_resolution_is_independent(self):
        index = idx({
            "A": {"1.0.0": {"C": "^1.0.0"}, "2.0.0": {"C": "^2.0.0"}},
            "B": {"1.0.0": {"C": "^1.0.0"}},
            "C": {"1.0.0": {}, "2.0.0": {}},
        })
        reqs = {"A": "*", "B": "*"}
        first = resolve(index, reqs)
        second = resolve(index, reqs)
        self.assertEqual(first, second)
        self.assertEqual(resolve(index, {"C": "*"}), {"C": "2.0.0"})


class PrereleaseFilterSymptoms(unittest.TestCase):
    def test_max_satisfying_skips_prerelease(self):
        self.assertEqual(max_satisfying(["1.5.0", "2.0.0-beta.1"], ">=1.0.0"), V("1.5.0"))
        self.assertEqual(max_satisfying(["1.5.0", "2.0.0-beta.1", "1.9.0-rc.1"], "^1.0.0"), V("1.5.0"))
        self.assertIsNone(max_satisfying(["2.0.0-beta.1"], ">=1.0.0"))

    def test_min_satisfying(self):
        self.assertEqual(min_satisfying(["1.0.0-rc.1", "1.2.0", "1.3.0"], ">=1.0.0-rc.1 <1.0.0 || >=1.1.0"), V("1.0.0-rc.1"))
        self.assertEqual(min_satisfying(["1.0.0-rc.1", "1.2.0"], ">=1.0.0"), V("1.2.0"))

    def test_filter(self):
        r = parse_range(">=1.0.0")
        self.assertEqual(r.filter(["0.9.0", "1.0.0", "1.1.0-alpha", "2.0.0-beta.1", "2.0.0"]), [V("1.0.0"), V("2.0.0")])

    def test_prerelease_allowed_when_mentioned(self):
        self.assertEqual(max_satisfying(["1.5.0", "2.0.0-beta.1", "2.0.0-beta.3"], ">=2.0.0-alpha.1"), V("2.0.0-beta.3"))
        r = parse_range(">=2.0.0-alpha.1")
        self.assertFalse(r.matches("2.1.0-beta.1"))
        self.assertEqual(r.filter(["2.1.0-beta.1"]), [])
        self.assertEqual(parse_range("^1.2.3-beta.1").filter(["1.2.3-beta.2", "1.3.0-beta.1"]), [V("1.2.3-beta.2")])

    def test_union_set_scoping(self):
        r = parse_range(">=1.0.0 <2.0.0 || >=3.0.0-beta.1 <3.0.0")
        self.assertEqual(r.filter(["1.5.0-rc.1", "3.0.0-beta.2", "3.0.0-rc.1"]), [V("3.0.0-beta.2"), V("3.0.0-rc.1")])

    def test_resolver_ignores_prerelease(self):
        index = idx({"a": {"1.5.0": {}, "2.0.0-beta.1": {}}})
        self.assertEqual(resolve(index, {"a": ">=1.0.0"})["a"], V("1.5.0"))
        self.assertEqual(resolve(index, {"a": "*"})["a"], V("1.5.0"))
        self.assertEqual(resolve(index, {"a": ">=2.0.0-beta.0"})["a"], V("2.0.0-beta.1"))

    def test_resolver_dependency_range(self):
        index = idx({"app": {"1.0.0": {"a": ">=1.0.0"}}, "a": {"1.5.0": {}, "2.0.0-beta.1": {}}})
        self.assertEqual(resolve(index, {"app": "*"}), {"app": "1.0.0", "a": "1.5.0"})
        self.assertEqual([r.version for r in index.candidates("a", [parse_range(">=1.0.0")])], [V("1.5.0")])

    def test_outdated_ignores_prerelease_latest(self):
        index = idx({"a": {"1.0.0": {}, "1.5.0": {}, "2.0.0-beta.1": {}}})
        res = resolve(index, {"a": "1.0.0"})
        self.assertEqual(outdated(res, index), [("a", V("1.0.0"), V("1.5.0"))])


class ScopedNameSymptoms(unittest.TestCase):
    def setUp(self):
        self.index = idx({
            "@org/lib": {"1.2.0": {}, "1.3.0": {"util": "^1.0.0"}},
            "util": {"1.0.0": {}},
            "app": {"1.0.0": {"@org/lib": "^1.2.0"}},
        })

    def test_lockfile_roundtrip(self):
        res = resolve(self.index, {"app": "*"})
        text = dump(res)
        self.assertEqual(text.splitlines()[1:], ["@org/lib@1.3.0", "app@1.0.0", "util@1.0.0"])
        self.assertEqual(load(text), res)
        self.assertEqual(load(text).names(), ["@org/lib", "app", "util"])

    def test_load_scoped_line(self):
        res = load("# c\n\n@org/lib@1.2.3-beta.1+b5\n@a/b@0.0.1\nplain@2.0.0\n")
        self.assertEqual(res["@org/lib"], V("1.2.3-beta.1"))
        self.assertEqual(res.names(), ["@a/b", "@org/lib", "plain"])

    def test_requirement_scoped(self):
        name, rng = parse_requirement("@org/lib@^1.2")
        self.assertEqual(name, "@org/lib")
        self.assertTrue(rng.matches("1.9.0"))
        self.assertFalse(rng.matches("2.0.0"))
        name, rng = parse_requirement("@org/lib")
        self.assertEqual(name, "@org/lib")
        self.assertTrue(rng.matches("9.9.9"))

    def test_requirements_dict_and_resolve(self):
        reqs = parse_requirements(["app", "@org/lib@~1.2"])
        self.assertEqual(sorted(reqs), ["@org/lib", "app"])
        res = resolve(self.index, reqs)
        self.assertEqual(res["@org/lib"], V("1.2.0"))

    def test_unscoped_requirement_forms(self):
        self.assertEqual(parse_requirement("left-pad@^1.2")[0], "left-pad")
        self.assertEqual(str(parse_requirement("left-pad@^1.2")[1]), "^1.2")
        self.assertEqual(str(parse_requirement("left-pad")[1]), "*")
        self.assertEqual(str(parse_requirement("@org/lib@1.x || 3")[1]), "1.x || 3")

    def test_requirement_errors(self):
        for bad in ("", "  ", "@", "@@1.0"):
            with self.assertRaises(SpecError, msg=bad):
                parse_requirement(bad)
        with self.assertRaises(SpecError):
            parse_requirements(["a", "a@1"])
        with self.assertRaises(SpecError):
            parse_requirements(["@org/lib", "@org/lib@^1"])


class InstallOrderSymptoms(unittest.TestCase):
    def test_ready_packages_alphabetical(self):
        index = idx({
            "app": {"1.0.0": {"x": "*", "b": "*"}},
            "x": {"1.0.0": {}},
            "b": {"1.0.0": {"c": "*"}},
            "c": {"1.0.0": {}},
        })
        res = resolve(index, {"app": "*"})
        self.assertEqual(install_order(res, index), ["c", "b", "x", "app"])
        self.assertEqual(install_plan(res, index), "1. c@1.0.0\n2. b@1.0.0\n3. x@1.0.0\n4. app@1.0.0")

    def test_later_ready_beats_earlier_larger(self):
        index = idx({
            "root": {"1.0.0": {"d": "*", "a": "*"}},
            "d": {"1.0.0": {}},
            "a": {"1.0.0": {"e": "*"}},
            "e": {"1.0.0": {}},
        })
        res = resolve(index, {"root": "*"})
        self.assertEqual(install_order(res, index), ["d", "e", "a", "root"])

    def test_independent_sorted(self):
        index = idx({"m": {"1.0.0": {}}, "a": {"1.0.0": {}}, "z": {"1.0.0": {}}})
        res = resolve(index, {"z": "*", "a": "*", "m": "*"})
        self.assertEqual(install_order(res, index), ["a", "m", "z"])

    def test_lexicographically_smallest_big(self):
        index = idx({
            "top": {"1.0.0": {"p": "*", "q": "*", "r": "*"}},
            "p": {"1.0.0": {"s": "*"}}, "q": {"1.0.0": {}}, "r": {"1.0.0": {"q": "*", "t": "*"}},
            "s": {"1.0.0": {}}, "t": {"1.0.0": {}},
        })
        res = resolve(index, {"top": "*"})
        self.assertEqual(install_order(res, index), ["q", "s", "p", "t", "r", "top"])


class VersionRegression(unittest.TestCase):
    def test_parse_forms(self):
        self.assertEqual(V("1.2.3"), V("v1.2.3"))
        self.assertEqual(V(" 1.2.3 "), V("1.2.3"))
        self.assertEqual(V("1.2.3+build.5").build, ("build", "5"))
        self.assertEqual(str(V("1.0.0-alpha.1")), "1.0.0-alpha.1")
        self.assertEqual(str(V("1.0.0+meta")), "1.0.0+meta")
        v = V("1.0.0")
        self.assertIs(Version.parse(v), v)

    def test_invalid(self):
        for bad in ("1.2", "1", "1.2.3.4", "a.b.c", "01.2.3", "1.2.3-", "1.2.3+", "", "1.2.x", None, 5):
            with self.assertRaises(VersionError, msg=repr(bad)):
                V(bad)

    def test_precedence(self):
        self.assertTrue(V("1.2.3") < V("1.10.0") < V("2.0.0"))
        self.assertTrue(V("1.0.0-rc.1") < V("1.0.0"))
        self.assertFalse(V("1.0.0") < V("1.0.0"))
        self.assertTrue(V("1.0.0") <= V("1.0.0"))
        self.assertTrue(V("2.0.0-alpha") > V("1.9.9"))
        self.assertEqual(V("1.0.0+a"), V("1.0.0+b"))
        self.assertTrue(V("1.0.0+a").identical(V("1.0.0+a")))
        self.assertFalse(V("1.0.0+a").identical(V("1.0.0+b")))
        self.assertEqual(len({V("1.0.0+a"), V("1.0.0+b"), V("1.0.1")}), 2)
        self.assertNotEqual(V("1.0.0-alpha"), V("1.0.0"))

    def test_bump_and_misc(self):
        v = V("1.2.3-beta+x")
        self.assertEqual(str(v.bump("major")), "2.0.0")
        self.assertEqual(str(v.bump("minor")), "1.3.0")
        self.assertEqual(str(v.bump("patch")), "1.2.4")
        with self.assertRaises(ValueError):
            v.bump("nope")
        self.assertTrue(v.is_prerelease())
        self.assertTrue(v.same_core(V("1.2.3")))
        with self.assertRaises(AttributeError):
            v.major = 3

    def test_errors_are_value_errors(self):
        with self.assertRaises(ValueError):
            V("x")
        with self.assertRaises(ValueError):
            parse_range("nonsense")


class RangeRegression(RangeCase):
    def test_comparators_and_spacing(self):
        self.check(">= 1.0.0 < 2.0.0", yes=["1.5.0"], no=["2.0.0"])
        self.check("  >=1.0.0   <2.0.0 ", yes=["1.0.0"], no=["0.1.0"])
        self.check("<1.0.0", yes=["0.9.9"], no=["1.0.0"])
        self.check("<=1.0.0", yes=["1.0.0"], no=["1.0.1"])
        self.check(">=1.2", yes=["1.2.0", "5.0.0"], no=["1.1.9"])
        self.check(">1.2.3", yes=["1.2.4"], no=["1.2.3"])

    def test_wildcards_and_empty(self):
        for spec in ("", "*", "x", " * ", "X"):
            self.check(spec, yes=["0.0.0", "3.4.5"])
        self.check("1.2.x", yes=["1.2.0", "1.2.9"], no=["1.3.0", "1.1.9"])
        self.check("1.2", yes=["1.2.5"], no=["1.3.0"])

    def test_hyphen_full(self):
        self.check("1.2.3 - 2.3.4", yes=["1.2.3", "2.0.0", "2.3.4"], no=["1.2.2", "2.3.5"])
        self.check("1.2 - 2.3.4", yes=["1.2.0"], no=["1.1.9"])

    def test_union(self):
        self.check("1.0.0 || 2.0.0", yes=["1.0.0", "2.0.0"], no=["1.5.0"])
        self.check("^1.0.0 || ^3.0.0", yes=["1.5.0", "3.1.0"], no=["2.0.0"])
        self.check(" || 1.0.0", yes=["5.0.0", "1.0.0"])

    def test_tilde_forms(self):
        self.check("~1.2.3-beta.2", yes=["1.2.3-beta.4", "1.2.9"], no=["1.2.3-beta.1", "1.3.0"])
        self.check("~ 1.2.3", yes=["1.2.5"], no=["1.3.0"])

    def test_prerelease_rule(self):
        r = parse_range(">=1.0.0")
        self.assertFalse(r.matches("2.0.0-beta.1"))
        self.assertTrue(r.matches("2.0.0"))
        self.assertTrue(parse_range(">=1.0.0-alpha").matches("1.0.0-beta"))
        self.assertFalse(parse_range(">=1.0.0-alpha").matches("1.0.1-beta"))
        self.assertTrue(parse_range("1.0.0-beta.1").matches("1.0.0-beta.1"))

    def test_range_objects(self):
        r = parse_range("^1.2.3")
        self.assertIs(parse_range(r), r)
        self.assertEqual(str(r), "^1.2.3")
        self.assertEqual(str(parse_range("")), "*")
        self.assertTrue(r.matches(V("1.5.0")))

    def test_errors(self):
        for bad in ("abc", "1.2.3.4", "^", ">=", "1.2.x-beta", "~", "1.2.3 -", "= =1", 5, None, "1..2"):
            with self.assertRaises(SpecError, msg=repr(bad)):
                parse_range(bad)

    def test_satisfies(self):
        self.assertTrue(satisfies("1.5.0", "^1.0.0"))
        self.assertFalse(satisfies("2.0.0", "^1.0.0"))
        self.assertTrue(satisfies(V("1.5.0"), "1.x"))
        self.assertIsNone(max_satisfying([], "*"))
        self.assertIsNone(min_satisfying(["1.0.0"], "^2"))


class IndexRegression(unittest.TestCase):
    def test_basics(self):
        index = PackageIndex()
        index.add("a", "1.0.0")
        index.add("a", "1.10.0", {"b": "^1"})
        index.add("a", "1.2.0")
        self.assertEqual(index.names(), ["a"])
        self.assertIn("a", index)
        self.assertNotIn("zzz", index)
        self.assertEqual([str(v) for v in index.versions("a")], ["1.10.0", "1.2.0", "1.0.0"])
        self.assertEqual(index.release("a", "1.10.0").deps["b"].matches("1.5.0"), True)
        self.assertEqual(index.versions("missing"), [])

    def test_errors(self):
        index = PackageIndex()
        index.add("a", "1.0.0")
        with self.assertRaises(PkgresError):
            index.add("a", "1.0.0")
        with self.assertRaises(PkgresError):
            index.release("a", "2.0.0")
        with self.assertRaises(VersionError):
            index.add("a", "oops")
        with self.assertRaises(SpecError):
            index.add("b", "1.0.0", {"c": "^"})

    def test_build_metadata_is_same_release(self):
        index = PackageIndex()
        index.add("a", "1.0.0+x")
        with self.assertRaises(PkgresError):
            index.add("a", "1.0.0+y")

    def test_candidates_multiple_ranges(self):
        index = idx({"a": {"1.0.0": {}, "1.5.0": {}, "2.0.0": {}}})
        got = index.candidates("a", [parse_range(">=1.0.0"), parse_range("<2.0.0")])
        self.assertEqual([str(r.version) for r in got], ["1.5.0", "1.0.0"])
        self.assertEqual(index.candidates("nope", [parse_range("*")]), [])


class ResolverRegression(unittest.TestCase):
    def test_highest_and_shared_dependency(self):
        index = idx({
            "app": {"1.0.0": {"a": "^1.0.0", "b": "^1.0.0"}},
            "a": {"1.0.0": {"c": ">=1.0.0 <3.0.0"}, "1.1.0": {"c": "^2.0.0"}},
            "b": {"1.0.0": {"c": "^1.0.0"}, "1.2.0": {"c": "<2.0.0"}},
            "c": {"1.0.0": {}, "1.4.0": {}, "2.0.0": {}, "3.0.0": {}},
        })
        res = resolve(index, {"app": "*"})
        self.assertEqual(res, {"app": "1.0.0", "a": "1.0.0", "b": "1.2.0", "c": "1.4.0"})

    def test_empty_and_missing(self):
        index = idx({"a": {"1.0.0": {}}})
        self.assertEqual(len(resolve(index, {})), 0)
        with self.assertRaises(ResolutionError):
            resolve(index, {"missing": "*"})
        with self.assertRaises(ResolutionError):
            resolve(index, {"a": ">=2.0.0"})
        with self.assertRaises(ResolutionError):
            resolve(idx({"a": {"1.0.0": {"ghost": "*"}}}), {"a": "*"})

    def test_requirement_objects(self):
        index = idx({"a": {"1.0.0": {}, "2.0.0": {}}})
        self.assertEqual(resolve(index, {"a": parse_range("^1")})["a"], V("1.0.0"))

    def test_resolution_object(self):
        index = idx({"b": {"1.0.0": {}}, "a": {"2.0.0": {}}})
        res = resolve(index, {"b": "*", "a": "*"})
        self.assertEqual(res.names(), ["a", "b"])
        self.assertEqual([(n, str(v)) for n, v in res.items()], [("a", "2.0.0"), ("b", "1.0.0")])
        self.assertIn("a", res)
        self.assertEqual(len(res), 2)
        self.assertEqual(res.as_dict()["a"], V("2.0.0"))
        self.assertNotEqual(res, {"a": "2.0.0"})
        self.assertEqual(format_resolution(res), "a  2.0.0\nb  1.0.0")

    def test_diamond_picks_common_version(self):
        index = idx({
            "top": {"1.0.0": {"l": "*", "r": "*"}},
            "l": {"1.0.0": {"base": "<=1.5.0"}},
            "r": {"1.0.0": {"base": ">=1.2.0"}},
            "base": {"1.0.0": {}, "1.3.0": {}, "1.6.0": {}},
        })
        self.assertEqual(resolve(index, {"top": "*"})["base"], V("1.3.0"))


class GraphRegression(unittest.TestCase):
    def setUp(self):
        self.index = idx({
            "app": {"1.0.0": {"lib": "*", "util": "*"}},
            "lib": {"1.0.0": {"util": "*"}},
            "util": {"1.0.0": {}},
        })
        self.res = resolve(self.index, {"app": "*"})

    def test_maps(self):
        self.assertEqual(dependency_map(self.res, self.index), {"app": ["lib", "util"], "lib": ["util"], "util": []})
        self.assertEqual(dependents(self.res, self.index, "util"), ["app", "lib"])
        self.assertEqual(dependents(self.res, self.index, "app"), [])
        self.assertEqual(depth(self.res, self.index, "app"), 2)
        self.assertEqual(depth(self.res, self.index, "util"), 0)

    def test_order(self):
        self.assertEqual(install_order(self.res, self.index), ["util", "lib", "app"])

    def test_cycles(self):
        index = idx({"a": {"1.0.0": {"b": "*"}}, "b": {"1.0.0": {"c": "*"}}, "c": {"1.0.0": {"a": "*"}}})
        res = resolve(index, {"a": "*"})
        with self.assertRaises(CycleError) as cm:
            install_order(res, index)
        self.assertEqual(cm.exception.cycle, ["a", "b", "c", "a"])
        self.assertIsNone(find_cycle({"a": [], "b": ["a"]}))
        self.assertEqual(find_cycle({"a": ["a"]}), ["a", "a"])


class ReportAndLockRegression(unittest.TestCase):
    def setUp(self):
        self.index = idx({
            "app": {"1.0.0": {"lib": "*"}},
            "lib": {"1.0.0": {"util": "*"}, "1.1.0": {"util": "*"}},
            "util": {"1.0.0": {}},
        })
        self.res = resolve(self.index, {"app": "*"})

    def test_explain(self):
        self.assertEqual(explain(self.res, self.index, "util"), "util@1.0.0 (required by lib@1.1.0)")
        self.assertEqual(explain(self.res, self.index, "app"), "app@1.0.0 (required directly)")
        self.assertEqual(explain(self.res, self.index, "zzz"), "zzz is not installed")

    def test_tree(self):
        self.assertEqual(tree(self.res, self.index, ["app"]), "app@1.0.0\n  lib@1.1.0\n    util@1.0.0")

    def test_outdated(self):
        old = resolve(self.index, {"app": "*", "lib": "1.0.0"})
        self.assertEqual(outdated(old, self.index), [("lib", V("1.0.0"), V("1.1.0"))])
        self.assertEqual(outdated(self.res, self.index), [])

    def test_lockfile_errors_and_format(self):
        text = dump(self.res)
        self.assertTrue(text.startswith("# pkgres lockfile v1\n"))
        self.assertEqual(load(text), self.res)
        for bad in ("name\n", "name@\n", "@1.0.0\n", "a@x.y\n"):
            with self.assertRaises(LockfileError, msg=bad):
                load(bad)
        self.assertEqual(len(load("")), 0)

    def test_diff(self):
        old = resolve(self.index, {"app": "*", "lib": "1.0.0"})
        index2 = idx({"app": {"1.0.0": {"lib": "*", "extra": "*"}}, "lib": {"1.1.0": {}}, "extra": {"2.0.0": {}}})
        new = resolve(index2, {"app": "*"})
        changes = diff(old, new)
        self.assertEqual([(c.name, c.kind) for c in changes], [("extra", "added"), ("lib", "upgraded"), ("util", "removed")])
        self.assertEqual(summarize(changes), {"added": 1, "removed": 1, "upgraded": 1, "downgraded": 0})
        self.assertEqual(format_changes(changes), "+ extra 2.0.0\n^ lib 1.0.0 -> 1.1.0\n- util 1.0.0")
        self.assertEqual(diff(old, old), [])
        self.assertEqual(Change("a", None, V("1.0.0")), Change("a", None, V("1.0.0")))


if __name__ == "__main__":
    unittest.main()
