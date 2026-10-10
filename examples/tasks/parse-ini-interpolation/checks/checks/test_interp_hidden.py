import unittest

from inix import Config, InterpolationError, MissingError, dumps


def cfg(text):
    return Config.from_string(text)


class Basics(unittest.TestCase):
    def test_exception_type(self):
        self.assertTrue(issubclass(InterpolationError, ValueError))

    def test_same_section(self):
        c = cfg("[s]\nhost = h\nport = 80\nurl = http://${host}:${port}/api\n")
        self.assertEqual(c.get("s", "url"), "http://h:80/api")

    def test_cross_section(self):
        c = cfg("[a]\nx = ${b:y}!\n[b]\ny = why\n")
        self.assertEqual(c.get("a", "x"), "why!")

    def test_referenced_value_uses_its_own_section(self):
        c = cfg("[a]\nx = ${b:x}\ny = A-y\n[b]\nx = ${y}\ny = B-y\n")
        self.assertEqual(c.get("a", "x"), "B-y")

    def test_chain(self):
        c = cfg("[s]\na = 1\nb = ${a}2\nc = ${b}3\nd = ${c}4\n")
        self.assertEqual(c.get("s", "d"), "1234")

    def test_repeated_reference_is_not_a_cycle(self):
        c = cfg("[s]\na = x\nb = ${a}${a}\nc = ${b}-${b}\n")
        self.assertEqual(c.get("s", "c"), "xx-xx")

    def test_whitespace_in_name(self):
        c = cfg("[s]\nhost = h\nu = ${ host }|${  s:host  }\n")
        self.assertEqual(c.get("s", "u"), "h|h")

    def test_multiline_value(self):
        c = cfg("[s]\nn = X\nblock = a ${n}\n    b ${n}\n")
        self.assertEqual(c.get("s", "block"), "a X\nb X")

    def test_no_references_unchanged(self):
        c = cfg("[s]\nv = plain text, 100%\n")
        self.assertEqual(c.get("s", "v"), "plain text, 100%")


class Escapes(unittest.TestCase):
    def test_double_dollar(self):
        c = cfg("[s]\nprice = $$5 and $$$$\n")
        self.assertEqual(c.get("s", "price"), "$5 and $$")

    def test_escaped_brace_is_not_reference(self):
        c = cfg("[s]\nx = $${y}\ny = 1\n")
        self.assertEqual(c.get("s", "x"), "${y}")

    def test_lone_dollar_literal(self):
        c = cfg("[s]\na = $\nb = cost $5\nc = end$\nd = $ {x}\n")
        self.assertEqual(c.get("s", "a"), "$")
        self.assertEqual(c.get("s", "b"), "cost $5")
        self.assertEqual(c.get("s", "c"), "end$")
        self.assertEqual(c.get("s", "d"), "$ {x}")

    def test_triple_dollar_then_brace(self):
        c = cfg("[s]\nx = $$${y}\ny = 1\n")
        self.assertEqual(c.get("s", "x"), "$1")

    def test_referenced_text_not_rescanned(self):
        c = cfg("[s]\nraw = $${y}\ny = 1\nz = <${raw}>\n")
        self.assertEqual(c.get("s", "z"), "<${y}>")

    def test_referenced_dollar_dollar_collapses_once(self):
        c = cfg("[s]\na = $$5\nb = ${a}\nc = ${b}\n")
        self.assertEqual(c.get("s", "c"), "$5")


class Defaults(unittest.TestCase):
    def test_default_for_missing_key(self):
        c = cfg("[s]\nx = ${nope|fallback}\n")
        self.assertEqual(c.get("s", "x"), "fallback")

    def test_default_for_missing_section(self):
        c = cfg("[s]\nx = ${zz:k|dflt}\n")
        self.assertEqual(c.get("s", "x"), "dflt")

    def test_empty_default(self):
        c = cfg("[s]\nx = a${nope|}b\n")
        self.assertEqual(c.get("s", "x"), "ab")

    def test_default_not_stripped(self):
        c = cfg("[s]\nx = [${nope| a b }]\n")
        self.assertEqual(c.get("s", "x"), "[ a b ]")

    def test_default_not_interpolated(self):
        c = cfg("[s]\nk = v\nx = ${nope|$k and $$}\n")
        self.assertEqual(c.get("s", "x"), "$k and $$")

    def test_default_splits_at_first_pipe(self):
        c = cfg("[s]\nx = ${nope|a|b}\n")
        self.assertEqual(c.get("s", "x"), "a|b")

    def test_default_ignored_when_key_exists(self):
        c = cfg("[s]\nk = real\nx = ${k|other}\n")
        self.assertEqual(c.get("s", "x"), "real")

    def test_existing_empty_value_beats_default(self):
        c = cfg("[s]\nk =\nx = [${k|other}]\n")
        self.assertEqual(c.get("s", "x"), "[]")


class Errors(unittest.TestCase):
    def test_missing_key(self):
        c = cfg("[s]\nx = ${nokey}\n")
        with self.assertRaises(InterpolationError) as ctx:
            c.get("s", "x")
        self.assertIn("nokey", str(ctx.exception))

    def test_missing_section(self):
        c = cfg("[s]\nx = ${gone:k}\n")
        with self.assertRaises(InterpolationError) as ctx:
            c.get("s", "x")
        self.assertIn("gone:k", str(ctx.exception))

    def test_unterminated(self):
        c = cfg("[s]\nx = abc ${oops\n")
        with self.assertRaises(InterpolationError):
            c.get("s", "x")

    def test_empty_name(self):
        c = cfg("[s]\na = ${}\nb = ${  }\nc = ${|d}\n")
        for key in "abc":
            with self.assertRaises(InterpolationError):
                c.get("s", key)

    def test_self_reference(self):
        c = cfg("[s]\na = ${a}\n")
        with self.assertRaises(InterpolationError) as ctx:
            c.get("s", "a")
        self.assertIn("cycle", str(ctx.exception))

    def test_cycle_with_default_still_fails(self):
        c = cfg("[s]\na = ${a|x}\nb = ${c|x}\nc = ${b|x}\n")
        for key in "abc":
            with self.assertRaises(InterpolationError) as ctx:
                c.get("s", key)
            self.assertIn("cycle", str(ctx.exception))

    def test_cross_section_cycle(self):
        c = cfg("[a]\nx = ${b:y}\n[b]\ny = ${a:x}\n")
        with self.assertRaises(InterpolationError) as ctx:
            c.get("a", "x")
        self.assertIn("cycle", str(ctx.exception))

    def test_error_in_referenced_value_beats_default(self):
        c = cfg("[s]\nbad = ${nope}\nx = ${bad|safe}\n")
        with self.assertRaises(InterpolationError):
            c.get("s", "x")

    def test_fallback_does_not_hide_interpolation_error(self):
        c = cfg("[s]\nx = ${nope}\n")
        with self.assertRaises(InterpolationError):
            c.get("s", "x", fallback="f")
        self.assertEqual(c.get("s", "absent", fallback="f"), "f")

    def test_missing_key_itself_still_missing_error(self):
        c = cfg("[s]\nx = 1\n")
        with self.assertRaises(MissingError):
            c.get("s", "absent")


class RawItemsTyped(unittest.TestCase):
    def test_raw_never_raises(self):
        c = cfg("[s]\na = ${a}\nb = ${nope}\nc = $$x ${\n")
        self.assertEqual(c.get("s", "a", raw=True), "${a}")
        self.assertEqual(c.get("s", "b", raw=True), "${nope}")
        self.assertEqual(c.get("s", "c", raw=True), "$$x ${")

    def test_items(self):
        c = cfg("[s]\nh = host\nu = http://${h}\ne = $$\n")
        self.assertEqual(c.items("s"), {"h": "host", "u": "http://host", "e": "$"})
        self.assertEqual(c.items("s", raw=True)["u"], "http://${h}")

    def test_items_raises_on_bad_value(self):
        c = cfg("[s]\nok = 1\nbad = ${zip}\n")
        with self.assertRaises(InterpolationError):
            c.items("s")
        self.assertEqual(c.items("s", raw=True), {"ok": "1", "bad": "${zip}"})

    def test_typed_getters_use_interpolation(self):
        c = cfg("[s]\nbase = 40\nport = ${base}80\nratio = ${base}.5\nflag = ${yn}\nyn = On\n")
        self.assertEqual(c.getint("s", "port"), 4080)
        self.assertEqual(c.getfloat("s", "ratio"), 40.5)
        self.assertIs(c.getbool("s", "flag"), True)

    def test_typed_fallback(self):
        c = cfg("[s]\nx = 1\n")
        self.assertEqual(c.getint("s", "nope", fallback=3), 3)
        bad = cfg("[s]\nx = ${q}\n")
        with self.assertRaises(InterpolationError):
            bad.getint("s", "x", fallback=3)


class Writer(unittest.TestCase):
    TEXT = "[a]\nhost = h\nurl = http://${host}/$$x\nmulti = one\n    two ${host}\n[b]\nz = ${a:host}\n"

    def test_default_writes_raw(self):
        c = cfg(self.TEXT)
        out = dumps(c)
        self.assertIn("url = http://${host}/$$x", out)
        self.assertEqual(Config.from_string(out).get("a", "url", raw=True), "http://${host}/$$x")

    def test_resolved(self):
        c = cfg(self.TEXT)
        out = dumps(c, resolved=True)
        self.assertEqual(
            out.replace("\r\n", "\n"),
            "[a]\nhost = h\nurl = http://h/$x\nmulti = one\n    two h\n\n[b]\nz = h\n",
        )

    def test_resolved_error_propagates(self):
        c = cfg("[a]\nx = ${no}\n")
        with self.assertRaises(InterpolationError):
            dumps(c, resolved=True)
        self.assertIn("${no}", dumps(c))


if __name__ == "__main__":
    unittest.main()
