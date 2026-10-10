import random
import time
import unittest

from textmerge import (MergeConflict, apply_diff, diff, join_lines, merge3, merge_text,
                       split_lines)


def L(*names):
    return [n + "\n" for n in names]


def lcs_len(a, b):
    n, m = len(a), len(b)
    prev = [0] * (m + 1)
    for i in range(n - 1, -1, -1):
        cur = [0] * (m + 1)
        for j in range(m - 1, -1, -1):
            cur[j] = prev[j + 1] + 1 if a[i] == b[j] else max(prev[j], cur[j + 1])
        prev = cur
    return prev[0]


class DiffTests(unittest.TestCase):
    def check(self, a, b):
        ops = diff(a, b)
        for op in ops:
            self.assertIn(op[0], ("=", "-", "+"))
        self.assertEqual(apply_diff(a, ops), b)
        edits = sum(1 for o, _ in ops if o != "=")
        self.assertEqual(edits, len(a) + len(b) - 2 * lcs_len(a, b), (a, b, ops))
        return ops

    def test_empty_cases(self):
        self.assertEqual(diff([], []), [])
        self.assertEqual(diff([], ["a"]), [("+", "a")])
        self.assertEqual(diff(["a", "b"], []), [("-", "a"), ("-", "b")])
        self.assertEqual(diff(["a"], ["a"]), [("=", "a")])

    def test_simple_replace(self):
        ops = self.check(list("abcd"), list("abxd"))
        self.assertEqual([o for o in ops if o[0] == "="], [("=", "a"), ("=", "b"), ("=", "d")])

    def test_paper_example(self):
        self.check(list("ABCABBA"), list("CBABAC"))

    def test_all_different(self):
        self.check(list("abc"), list("xyz"))

    def test_duplicates_minimal(self):
        self.check(list("aaaa"), list("aa"))
        self.check(list("abab"), list("baba"))
        self.check(list("aabbaabb"), list("bbaabbaa"))

    def test_random_small_alphabet(self):
        rng = random.Random(51)
        for _ in range(2500):
            a = [rng.choice("abc") for _ in range(rng.randrange(14))]
            b = [rng.choice("abc") for _ in range(rng.randrange(14))]
            self.check(a, b)

    def test_random_mutations(self):
        rng = random.Random(52)
        for _ in range(600):
            a = [rng.choice("abcdefgh") for _ in range(rng.randrange(40))]
            b = list(a)
            for _ in range(rng.randrange(6)):
                p = rng.randrange(len(b) + 1)
                r = rng.random()
                if r < 0.4 and p < len(b):
                    del b[p]
                elif r < 0.8:
                    b.insert(p, rng.choice("abcdefgh"))
                elif p < len(b):
                    b[p] = rng.choice("abcdefgh")
            self.check(a, b)

    def check_diff(self, a, b):
        self.check(a, b)

    def test_ops_hold_the_original_lines(self):
        a = ["x\n", "y\n"]
        b = ["y\n", "z\n"]
        ops = diff(a, b)
        self.assertEqual([l for o, l in ops if o in "=-"], a)
        self.assertEqual([l for o, l in ops if o in "=+"], b)

    def test_does_not_mutate_inputs(self):
        a, b = list("abc"), list("bcd")
        diff(a, b)
        self.assertEqual((a, b), (list("abc"), list("bcd")))

    def test_large_with_few_edits_is_fast(self):
        rng = random.Random(53)
        a = ["line %d\n" % i for i in range(40000)]
        b = list(a)
        for _ in range(150):
            p = rng.randrange(len(b))
            r = rng.random()
            if r < 0.33:
                del b[p]
            elif r < 0.66:
                b.insert(p, "new %d\n" % rng.randrange(10 ** 9))
            else:
                b[p] = "chg %d\n" % rng.randrange(10 ** 9)
        t = time.perf_counter()
        ops = diff(a, b)
        elapsed = time.perf_counter() - t
        self.assertEqual(apply_diff(a, ops), b)
        self.assertLessEqual(sum(1 for o, _ in ops if o != "="), 300)
        self.assertLess(elapsed, 5.0)

    def test_large_block_replace_is_fast(self):
        a = ["a%d\n" % i for i in range(20000)]
        b = a[:9000] + ["b%d\n" % i for i in range(400)] + a[9300:]
        t = time.perf_counter()
        ops = diff(a, b)
        elapsed = time.perf_counter() - t
        self.assertEqual(apply_diff(a, ops), b)
        self.assertEqual(sum(1 for o, _ in ops if o != "="), 700)
        self.assertLess(elapsed, 5.0)


class Merge3Basics(unittest.TestCase):
    def test_non_overlapping_changes_merge(self):
        base = L("a", "b", "c", "d", "e")
        ours = L("a", "B", "c", "d", "e")
        theirs = L("a", "b", "c", "d", "E")
        r = merge3(base, ours, theirs)
        self.assertEqual((r.lines, r.conflicts), (L("a", "B", "c", "d", "E"), 0))
        self.assertTrue(r.clean)
        self.assertEqual(r.text, "a\nB\nc\nd\nE\n")

    def test_overlapping_conflict_format(self):
        base = L("a", "b", "c")
        r = merge3(base, L("a", "X", "c"), L("a", "Y", "c"))
        self.assertEqual(r.text, "a\n<<<<<<< ours\nX\n=======\nY\n>>>>>>> theirs\nc\n")
        self.assertEqual(r.conflicts, 1)
        self.assertFalse(r.clean)

    def test_diff3_style_and_labels(self):
        base = L("a", "b", "c")
        r = merge3(base, L("a", "X", "c"), L("a", "Y", "c"), labels=("HEAD", "ancestor", "feature"), style="diff3")
        self.assertEqual(r.text, "a\n<<<<<<< HEAD\nX\n||||||| ancestor\nb\n=======\nY\n>>>>>>> feature\nc\n")
        r = merge3(base, L("a", "X", "c"), L("a", "Y", "c"), labels=("L", "B", "R"))
        self.assertEqual(r.text, "a\n<<<<<<< L\nX\n=======\nY\n>>>>>>> R\nc\n")

    def test_invalid_style(self):
        with self.assertRaises(ValueError):
            merge3([], [], [], style="zdiff3")

    def test_adjacent_changes_conflict(self):
        base = L("a", "b", "c", "d")
        r = merge3(base, L("a", "B", "c", "d"), L("a", "b", "C", "d"))
        self.assertEqual(r.conflicts, 1)
        self.assertEqual(r.text, "a\n<<<<<<< ours\nB\nc\n=======\nb\nC\n>>>>>>> theirs\nd\n")

    def test_separated_changes_do_not_conflict(self):
        base = L("a", "b", "c", "d")
        r = merge3(base, L("A", "b", "c", "d"), L("a", "b", "C", "d"))
        self.assertEqual((r.text, r.conflicts), ("A\nb\nC\nd\n", 0))

    def test_identical_changes_are_clean(self):
        base = L("a", "b", "c")
        r = merge3(base, L("a", "X", "c"), L("a", "X", "c"))
        self.assertEqual((r.lines, r.conflicts), (L("a", "X", "c"), 0))
        r = merge3(base, L("a", "c"), L("a", "c"))
        self.assertEqual((r.lines, r.conflicts), (L("a", "c"), 0))
        r = merge3(base, L("a", "b", "c", "n"), L("a", "b", "c", "n"))
        self.assertEqual((r.lines, r.conflicts), (L("a", "b", "c", "n"), 0))

    def test_insertions_at_same_point(self):
        base = L("a", "b")
        r = merge3(base, L("a", "X", "b"), L("a", "Y", "b"))
        self.assertEqual(r.text, "a\n<<<<<<< ours\nX\n=======\nY\n>>>>>>> theirs\nb\n")
        r = merge3(base, L("a", "X", "b"), L("a", "X", "b"))
        self.assertEqual(r.text, "a\nX\nb\n")

    def test_insertion_touching_edit(self):
        base = L("a", "b", "c")
        # ours inserts before b, theirs rewrites b: ranges touch
        r = merge3(base, L("a", "X", "b", "c"), L("a", "B", "c"))
        self.assertEqual(r.text, "a\n<<<<<<< ours\nX\nb\n=======\nB\n>>>>>>> theirs\nc\n")
        # insertion after b, theirs rewrites b: touches too
        r = merge3(base, L("a", "b", "X", "c"), L("a", "B", "c"))
        self.assertEqual(r.text, "a\n<<<<<<< ours\nb\nX\n=======\nB\n>>>>>>> theirs\nc\n")
        # insertion one line away does not touch
        r = merge3(base, L("a", "b", "c", "X"), L("a", "B", "c"))
        self.assertEqual((r.text, r.conflicts), ("a\nB\nc\nX\n", 0))

    def test_delete_vs_edit_conflict(self):
        base = L("a", "b", "c")
        r = merge3(base, L("a", "c"), L("a", "B", "c"))
        self.assertEqual(r.text, "a\n<<<<<<< ours\n=======\nB\n>>>>>>> theirs\nc\n")
        r = merge3(base, L("a", "c"), L("a", "B", "c"), style="diff3")
        self.assertEqual(r.text, "a\n<<<<<<< ours\n||||||| base\nb\n=======\nB\n>>>>>>> theirs\nc\n")

    def test_one_sided_changes(self):
        base = L("a", "b", "c")
        other = L("a", "Z", "c", "d")
        for style in ("merge", "diff3"):
            self.assertEqual(merge3(base, base, other, style=style).lines, other)
            self.assertEqual(merge3(base, other, base, style=style).lines, other)
            self.assertEqual(merge3(base, base, base, style=style).lines, base)

    def test_empty_files(self):
        self.assertEqual(merge3([], [], []).lines, [])
        self.assertEqual(merge3([], L("x"), []).lines, L("x"))
        self.assertEqual(merge3([], L("x"), L("x")).lines, L("x"))
        r = merge3([], L("x"), L("y"))
        self.assertEqual(r.text, "<<<<<<< ours\nx\n=======\ny\n>>>>>>> theirs\n")
        self.assertEqual(merge3(L("a"), [], []).lines, [])
        r = merge3(L("a"), [], L("a", "b"))
        self.assertEqual(r.text, "<<<<<<< ours\n=======\na\nb\n>>>>>>> theirs\n")
        r = merge3(L("a"), [], L("b"))
        self.assertEqual(r.text, "<<<<<<< ours\n=======\nb\n>>>>>>> theirs\n")

    def test_multiple_conflicts_counted(self):
        base = L("a", "b", "c", "d", "e")
        r = merge3(base, L("a", "X", "c", "Y", "e"), L("a", "P", "c", "Q", "e"))
        self.assertEqual(r.conflicts, 2)
        self.assertEqual(r.text.count("<<<<<<<"), 2)
        self.assertEqual(r.text.count(">>>>>>>"), 2)

    def test_transitive_cluster(self):
        base = L("a", "b", "c", "d", "e", "f")
        # ours rewrites b..c (one hunk) and e; theirs rewrites d: d touches c's end and e's start
        ours = L("a", "X", "d", "Y", "f")
        theirs = L("a", "b", "c", "D", "e", "f")
        r = merge3(base, ours, theirs)
        self.assertEqual(r.conflicts, 1)
        self.assertEqual(
            r.text,
            "a\n<<<<<<< ours\nX\nd\nY\n=======\nb\nc\nD\ne\n>>>>>>> theirs\nf\n")

    def test_common_prefix_and_suffix_leave_the_conflict(self):
        base = L("a", "b", "c")
        r = merge3(base, L("a", "N", "X", "c"), L("a", "N", "Y", "c"))
        self.assertEqual(r.text, "a\nN\n<<<<<<< ours\nX\n=======\nY\n>>>>>>> theirs\nc\n")
        r = merge3(base, L("a", "X", "M", "c"), L("a", "Y", "M", "c"))
        self.assertEqual(r.text, "a\n<<<<<<< ours\nX\n=======\nY\n>>>>>>> theirs\nM\nc\n")
        r = merge3(base, L("a", "N", "X", "M", "c"), L("a", "N", "Y", "Z", "M", "c"), style="diff3")
        self.assertEqual(
            r.text, "a\nN\n<<<<<<< ours\nX\n||||||| base\nb\n=======\nY\nZ\n>>>>>>> theirs\nM\nc\n")
        self.assertEqual(r.conflicts, 1)

    def test_trim_prefix_first_then_suffix(self):
        base = L("a", "b", "c")
        r = merge3(base, L("a", "P", "P", "c"), L("a", "P", "c"))
        self.assertEqual(r.text, "a\nP\n<<<<<<< ours\nP\n=======\n>>>>>>> theirs\nc\n")
        r = merge3(base, L("a", "P", "c"), L("a", "P", "P", "c"))
        self.assertEqual(r.text, "a\nP\n<<<<<<< ours\n=======\nP\n>>>>>>> theirs\nc\n")
        r = merge3(base, L("a", "P", "Q", "P", "c"), L("a", "P", "R", "P", "c"))
        self.assertEqual(r.text, "a\nP\n<<<<<<< ours\nQ\n=======\nR\n>>>>>>> theirs\nP\nc\n")

    def test_trimmed_suffix_may_lack_newline(self):
        r = merge3(["a\n", "b"], ["a\n", "X", "end"], ["a\n", "Y", "end"])
        self.assertEqual(r.text, "a\n<<<<<<< ours\nX\n=======\nY\n>>>>>>> theirs\nend")

    def test_cluster_with_equal_text_is_clean(self):
        base = L("a", "b", "c", "d")
        ours = L("a", "X", "c", "d")
        theirs = L("a", "X", "c", "d")
        self.assertEqual(merge3(base, ours, theirs).conflicts, 0)

    def test_missing_final_newline(self):
        base = ["a\n", "b"]
        r = merge3(base, ["a\n", "X"], ["a\n", "Y"])
        self.assertEqual(r.text, "a\n<<<<<<< ours\nX\n=======\nY\n>>>>>>> theirs\n")
        r = merge3(["a\n", "m\n", "b"], ["a\n", "m\n", "X"], ["A\n", "m\n", "b"])
        self.assertEqual(r.lines, ["A\n", "m\n", "X"])
        r = merge3(["a\n"], ["a\n", "b"], ["a\n", "b\n"])
        self.assertEqual(r.text, "a\n<<<<<<< ours\nb\n=======\nb\n>>>>>>> theirs\n")
        r = merge3(base, ["a\n", "b\n", "c"], ["a\n", "Q"], style="diff3")
        self.assertEqual(r.conflicts, 1)
        self.assertEqual(r.text, "a\n<<<<<<< ours\nb\nc\n||||||| base\nb\n=======\nQ\n>>>>>>> theirs\n")

    def test_inputs_not_mutated(self):
        base, ours, theirs = L("a", "b"), L("a", "X"), L("a", "Y")
        merge3(base, ours, theirs)
        self.assertEqual((base, ours, theirs), (L("a", "b"), L("a", "X"), L("a", "Y")))

    def test_lines_are_independent_of_input_lists(self):
        base = L("a", "b")
        r = merge3(base, base, L("a", "c"))
        r.lines.append("zzz")
        self.assertEqual(base, L("a", "b"))


class MergeTextApi(unittest.TestCase):
    def test_clean_line_level(self):
        base = "one\ntwo\nthree\nfour\nfive\n"
        ours = "ONE\ntwo\nthree\nfour\nfive\n"
        theirs = "one\ntwo\nthree\nfour\nFIVE\n"
        self.assertEqual(merge_text(base, ours, theirs), "ONE\ntwo\nthree\nfour\nFIVE\n")

    def test_conflict_raises_with_result(self):
        with self.assertRaises(MergeConflict) as cm:
            merge_text("a\nb\n", "a\nX\n", "a\nY\n")
        res = cm.exception.result
        self.assertEqual(res.conflicts, 1)
        self.assertEqual(res.text, "a\n<<<<<<< ours\nX\n=======\nY\n>>>>>>> theirs\n")

    def test_markers_mode(self):
        out = merge_text("a\nb\n", "a\nX\n", "a\nY\n", on_conflict="markers", labels=("mine", "orig", "yours"))
        self.assertEqual(out, "a\n<<<<<<< mine\nX\n=======\nY\n>>>>>>> yours\n")
        out = merge_text("a\nb\n", "a\nX\n", "a\nY\n", on_conflict="markers", labels=("mine", "orig", "yours"),
                         style="diff3")
        self.assertEqual(out, "a\n<<<<<<< mine\nX\n||||||| orig\nb\n=======\nY\n>>>>>>> yours\n")

    def test_bad_on_conflict(self):
        with self.assertRaises(ValueError):
            merge_text("a\n", "b\n", "c\n", on_conflict="ignore")

    def test_crlf_and_control_chars_stay_in_lines(self):
        base = "a\r\nb\x0cc\r\nd\r\n"
        ours = "A\r\nb\x0cc\r\nd\r\n"
        theirs = "a\r\nb\x0cc\r\nD\r\n"
        self.assertEqual(merge_text(base, ours, theirs), "A\r\nb\x0cc\r\nD\r\n")

    def test_old_file_level_behaviour(self):
        self.assertEqual(merge_text("a\n", "a\n", "b\n"), "b\n")
        self.assertEqual(merge_text("a\n", "b\n", "a\n"), "b\n")
        self.assertEqual(merge_text("a\n", "b\n", "b\n"), "b\n")
        with self.assertRaises(MergeConflict):
            merge_text("a\n", "b\n", "c\n")
        self.assertEqual(merge_text("", "x\n", ""), "x\n")


# ---------------- oracle: changes known by construction ----------------

def gen_side(rng, n, tag, fresh):
    hunks, pos = [], 0
    while pos <= n:
        if rng.random() < 0.28:
            kind = rng.choice(("ins", "del", "rep", "rep"))
            ln = 0 if kind == "ins" else min(rng.randrange(1, 4), n - pos)
            if kind != "ins" and ln == 0:
                break
            new = [] if kind == "del" else ["%s%d\n" % (tag, next(fresh)) for _ in range(rng.randrange(1, 4))]
            hunks.append((pos, pos + ln, new))
            pos = pos + ln + 1
        else:
            pos += 1
    return hunks


def side_text(base, hunks):
    out, pos = [], 0
    for b0, b1, new in hunks:
        out += base[pos:b0] + new
        pos = b1
    return out + base[pos:]


def counter():
    i = 0
    while True:
        yield i
        i += 1


def oracle_merge(base, oh, th, labels, style):
    allh = [(h, 0) for h in oh] + [(h, 1) for h in th]
    parent = list(range(len(allh)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, ((a0, a1, _), s) in enumerate(allh):
        for j, ((c0, c1, _), t) in enumerate(allh):
            if s != t and a0 <= c1 and c0 <= a1:
                parent[find(i)] = find(j)
    comps = {}
    for i in range(len(allh)):
        comps.setdefault(find(i), []).append(allh[i])
    regions = []
    for members in comps.values():
        lo = min(h[0] for h, _ in members)
        hi = max(h[1] for h, _ in members)
        regions.append((lo, hi, [h for h, s in members if s == 0], [h for h, s in members if s == 1]))
    regions.sort(key=lambda r: (r[0], r[1]))
    out, pos, conflicts = [], 0, 0
    for lo, hi, a, b in regions:
        out += base[pos:lo]
        pos = hi
        seg = base[lo:hi]

        def render(hs):
            res, p = [], lo
            for b0, b1, new in sorted(hs):
                res += base[p:b0] + new
                p = b1
            return res + base[p:hi]

        ot, tt = render(a), render(b)
        if ot == tt:
            out += ot
        elif not a:
            out += tt
        elif not b:
            out += ot
        else:
            conflicts += 1
            pre = 0
            while pre < min(len(ot), len(tt)) and ot[pre] == tt[pre]:
                pre += 1
            out += ot[:pre]
            ot, tt = ot[pre:], tt[pre:]
            suf = 0
            while suf < min(len(ot), len(tt)) and ot[len(ot) - 1 - suf] == tt[len(tt) - 1 - suf]:
                suf += 1
            tail = ot[len(ot) - suf:]
            ot, tt = ot[:len(ot) - suf], tt[:len(tt) - suf]
            out.append("<<<<<<< %s\n" % labels[0])
            out += ot
            if style == "diff3":
                out.append("||||||| %s\n" % labels[1])
                out += seg
            out.append("=======\n")
            out += tt
            out.append(">>>>>>> %s\n" % labels[2])
            out += tail
    return out + base[pos:], conflicts


class Oracle(unittest.TestCase):
    def run_cases(self, seed, count, maxn):
        rng = random.Random(seed)
        fresh = counter()
        clean = conflicted = 0
        for _ in range(count):
            n = rng.randrange(0, maxn)
            base = ["b%d\n" % i for i in range(n)]
            oh = gen_side(rng, n, "o", fresh)
            th = []
            for h in gen_side(rng, n, "t", fresh):
                th.append(h)
            # sometimes copy some of ours' hunks to theirs (identical changes)
            for h in oh:
                if rng.random() < 0.25:
                    th.append(h)
            th.sort()
            # keep same-side hunks separated by at least one base line
            cleaned, last_end = [], -1
            for h in th:
                if h[0] > last_end and not (cleaned and cleaned[-1] == h):
                    cleaned.append(h)
                    last_end = h[1]
            th = cleaned
            ours, theirs = side_text(base, oh), side_text(base, th)
            style = rng.choice(("merge", "diff3"))
            labels = rng.choice([("ours", "base", "theirs"), ("A", "B", "C"), ("HEAD", "merge base", "topic")])
            exp_lines, exp_conf = oracle_merge(base, oh, th, labels, style)
            got = merge3(base, ours, theirs, labels=labels, style=style)
            self.assertEqual((got.lines, got.conflicts), (exp_lines, exp_conf), (base, ours, theirs, style))
            if exp_conf:
                conflicted += 1
            else:
                clean += 1
            # the text API agrees
            txt = merge_text(join_lines(base), join_lines(ours), join_lines(theirs),
                             on_conflict="markers", labels=labels, style=style)
            self.assertEqual(txt, join_lines(exp_lines))
        self.assertGreater(clean, count // 5)
        self.assertGreater(conflicted, count // 8)

    def test_small(self):
        self.run_cases(61, 1500, 8)

    def test_medium(self):
        self.run_cases(62, 1200, 25)

    def test_dense_edits(self):
        self.run_cases(63, 800, 14)

    def test_large_merge_is_fast(self):
        rng = random.Random(64)
        fresh = counter()
        n = 30000
        base = ["b%d\n" % i for i in range(n)]

        def sparse(tag, offset):
            hs, pos = [], offset
            while pos < n - 5:
                hs.append((pos, pos + rng.randrange(0, 3), ["%s%d\n" % (tag, next(fresh))]))
                pos = hs[-1][1] + 1 + rng.randrange(150, 400)
            return hs

        oh, th = sparse("o", 10), sparse("t", 25)
        ours, theirs = side_text(base, oh), side_text(base, th)
        exp, conf = oracle_merge(base, oh, th, ("ours", "base", "theirs"), "merge")
        t = time.perf_counter()
        got = merge3(base, ours, theirs)
        self.assertLess(time.perf_counter() - t, 6.0)
        self.assertEqual((got.lines, got.conflicts), (exp, conf))

    def test_large_unchanged_sides(self):
        base = ["l%d\n" % i for i in range(60000)]
        t = time.perf_counter()
        r = merge3(base, base, base)
        self.assertLess(time.perf_counter() - t, 3.0)
        self.assertEqual((r.lines, r.conflicts), (base, 0))


def _more_merge_seeds():
    def mk(seed, n):
        def t(self):
            self.run_cases(seed, 250, n)
        return t

    for k, n in enumerate((8, 9, 12, 16, 20, 25)):
        setattr(Oracle, "test_seed_%d" % k, mk(70 + k, n))

    def mkd(seed):
        def t(self):
            rng = random.Random(seed)
            for _ in range(300):
                a = [rng.choice("abcd") for _ in range(rng.randrange(0, 16))]
                b = [rng.choice("abcd") for _ in range(rng.randrange(0, 16))]
                self.check_diff(a, b)
        return t

    for k in range(4):
        setattr(DiffTests, "test_random_seed_%d" % k, mkd(80 + k))


class Splitting(unittest.TestCase):
    def test_split_and_join_unchanged(self):
        for text in ["", "a", "a\n", "a\n\nb", "\n\n", "x\r\ny\rz\n"]:
            self.assertEqual(join_lines(split_lines(text)), text)
        self.assertEqual(split_lines("x\r\ny\rz\n"), ["x\r\n", "y\rz\n"])


_more_merge_seeds()


if __name__ == "__main__":
    unittest.main()
