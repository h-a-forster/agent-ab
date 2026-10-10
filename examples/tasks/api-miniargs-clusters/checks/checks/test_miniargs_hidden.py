import unittest

from miniargs import Option, Parser, Positional, UsageError


def base(**kw):
    return Parser(
        options=[
            Option("verbose", short="v", kind="count"),
            Option("quiet", short="q", kind="flag"),
            Option("output", short="o"),
            Option("include", short="I", kind="append"),
            Option("jobs", short="j", type=int, default=1),
            Option("force", short="f", kind="flag"),
        ],
        positionals=[Positional("files", many=True, required=False)],
        **kw,
    )


class EqualsForm(unittest.TestCase):
    def test_value(self):
        self.assertEqual(base().parse(["--output=out.txt"]).output, "out.txt")

    def test_empty_and_embedded_equals(self):
        self.assertEqual(base().parse(["--output="]).output, "")
        self.assertEqual(base().parse(["--output=a=b"]).output, "a=b")

    def test_typed(self):
        self.assertEqual(base().parse(["--jobs=8"]).jobs, 8)
        with self.assertRaises(UsageError) as cm:
            base().parse(["--jobs=eight"])
        self.assertIn("--jobs", str(cm.exception))

    def test_flag_and_count_reject_value(self):
        for argv in (["--quiet=1"], ["--verbose=2"], ["--force="]):
            with self.assertRaises(UsageError):
                base().parse(argv)

    def test_unknown_with_equals(self):
        with self.assertRaises(UsageError) as cm:
            base().parse(["--nope=1"])
        self.assertIn("nope", str(cm.exception))

    def test_append_with_equals(self):
        self.assertEqual(base().parse(["--include=a", "--include", "b"]).include, ["a", "b"])


class Clusters(unittest.TestCase):
    def test_flags_and_counts(self):
        ns = base().parse(["-vvqf"])
        self.assertEqual((ns.verbose, ns.quiet, ns.force), (2, True, True))

    def test_attached_value(self):
        self.assertEqual(base().parse(["-oout.txt"]).output, "out.txt")
        self.assertEqual(base().parse(["-vvIinc"]).include, ["inc"])

    def test_cluster_then_value_next_token(self):
        ns = base().parse(["-vo", "out.txt", "f"])
        self.assertEqual((ns.verbose, ns.output, ns.files), (1, "out.txt", ["f"]))

    def test_equals_is_literal_in_short_form(self):
        self.assertEqual(base().parse(["-o=x"]).output, "=x")

    def test_value_may_look_like_option(self):
        self.assertEqual(base().parse(["-o", "-v"]).output, "-v")
        self.assertEqual(base().parse(["--output", "--quiet"]).output, "--quiet")
        self.assertEqual(base().parse(["-fo", "--"]).output, "--")

    def test_missing_value(self):
        for argv in (["-o"], ["-vo"], ["--output"], ["-j"]):
            with self.assertRaises(UsageError):
                base().parse(argv)

    def test_unknown_letter(self):
        with self.assertRaises(UsageError) as cm:
            base().parse(["-vzq"])
        self.assertIn("-z", str(cm.exception))

    def test_typed_short_value(self):
        self.assertEqual(base().parse(["-j4"]).jobs, 4)
        with self.assertRaises(UsageError):
            base().parse(["-jx"])

    def test_value_option_after_letters_consumes_rest(self):
        ns = base().parse(["-vojq"])  # -o takes 'jq'
        self.assertEqual((ns.verbose, ns.output, ns.quiet), (1, "jq", False))


class Kinds(unittest.TestCase):
    def test_count_defaults_and_long(self):
        self.assertEqual(base().parse([]).verbose, 0)
        self.assertEqual(base().parse(["--verbose", "-v", "--verbose"]).verbose, 3)

    def test_append_default_and_independent(self):
        p = base()
        a = p.parse([])
        a.include.append("junk")
        self.assertEqual(p.parse([]).include, [])

    def test_append_default_copied(self):
        default = ["x"]
        p = Parser(options=[Option("inc", kind="append", default=default)])
        r = p.parse(["--inc", "y"])
        self.assertEqual(r.inc, ["y"])
        self.assertEqual(default, ["x"])
        self.assertEqual(p.parse([]).inc, ["x"])
        p.parse([]).inc.append("z")
        self.assertEqual(default, ["x"])

    def test_append_converts_each(self):
        p = Parser(options=[Option("n", short="n", kind="append", type=int)])
        self.assertEqual(p.parse(["-n1", "-n", "2", "--n=3"]).n, [1, 2, 3])
        with self.assertRaises(UsageError):
            p.parse(["-n1", "-nx"])

    def test_last_value_wins(self):
        self.assertEqual(base().parse(["-oa", "-ob"]).output, "b")

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            Option("x", kind="toggle")

    def test_required_still_enforced(self):
        p = Parser(options=[Option("token", short="t", required=True)])
        with self.assertRaises(UsageError):
            p.parse([])
        self.assertEqual(p.parse(["-tabc"]).token, "abc")


class WordsAndDoubleDash(unittest.TestCase):
    def test_double_dash(self):
        ns = base().parse(["-q", "--", "-v", "--output", "--", "x"])
        self.assertEqual(ns.files, ["-v", "--output", "--", "x"])
        self.assertEqual((ns.quiet, ns.verbose, ns.output), (True, 0, None))

    def test_double_dash_only(self):
        self.assertEqual(base().parse(["--"]).files, [])

    def test_double_dash_as_value_is_not_terminator(self):
        ns = base().parse(["--output", "--", "a"])
        self.assertEqual((ns.output, ns.files), ("--", ["a"]))

    def test_negative_numbers_and_dash(self):
        ns = base().parse(["-5", "-", "-3.25", "x"])
        self.assertEqual(ns.files, ["-5", "-", "-3.25", "x"])

    def test_negative_number_as_option_value(self):
        p = Parser(options=[Option("offset", short="d", type=int)], positionals=[Positional("n", type=float)])
        ns = p.parse(["-d", "-7", "-2.5"])
        self.assertEqual((ns.offset, ns.n), (-7, -2.5))

    def test_number_like_but_not_number_is_option(self):
        for tok in ("-5x", "-1.", "-.5"):
            with self.assertRaises(UsageError):
                base().parse([tok])

    def test_interleaved(self):
        ns = base().parse(["a", "-v", "b", "--output=o", "c"])
        self.assertEqual((ns.files, ns.verbose, ns.output), (["a", "b", "c"], 1, "o"))

    def test_old_errors_still_work(self):
        p = Parser(positionals=[Positional("src"), Positional("dst", required=False)])
        for argv in ([], ["a", "b", "c"], ["--zzz"]):
            with self.assertRaises(UsageError):
                p.parse(argv)
        self.assertIsNone(p.parse(["a"]).dst)


class Subcommands(unittest.TestCase):
    def make(self):
        add = Parser(options=[Option("force", short="f", kind="flag"), Option("verbose", short="v", kind="count")],
                     positionals=[Positional("name")])
        rm = Parser(options=[Option("recursive", short="r", kind="flag")], positionals=[Positional("paths", many=True)])
        return Parser(options=[Option("config", short="c", default="app.toml"), Option("debug", kind="flag")],
                      commands={"add": add, "rm": rm})

    def test_dispatch(self):
        ns = self.make().parse(["--config", "x.toml", "add", "-fvv", "thing"])
        self.assertEqual(ns.command, "add")
        self.assertEqual(ns.config, "x.toml")
        self.assertEqual((ns.sub.force, ns.sub.verbose, ns.sub.name), (True, 2, "thing"))
        self.assertTrue(ns.sub.command is None and ns.sub.sub is None)

    def test_defaults_on_parent(self):
        ns = self.make().parse(["rm", "-r", "a", "b"])
        self.assertEqual((ns.config, ns.debug, ns.command), ("app.toml", False, "rm"))
        self.assertEqual((ns.sub.recursive, ns.sub.paths), (True, ["a", "b"]))

    def test_no_commands_means_none(self):
        ns = base().parse([])
        self.assertIsNone(ns.command)
        self.assertIsNone(ns.sub)

    def test_parent_options_after_command_go_to_subparser(self):
        with self.assertRaises(UsageError) as cm:
            self.make().parse(["add", "--debug", "x"])
        self.assertIn("debug", str(cm.exception))

    def test_missing_command(self):
        for argv in ([], ["--debug"]):
            with self.assertRaises(UsageError):
                self.make().parse(argv)

    def test_unknown_command(self):
        with self.assertRaises(UsageError) as cm:
            self.make().parse(["push"])
        msg = str(cm.exception)
        self.assertIn("push", msg)
        self.assertIn("add", msg)
        self.assertIn("rm", msg)

    def test_double_dash_before_command(self):
        ns = self.make().parse(["--debug", "--", "rm", "-r", "f"])
        self.assertEqual((ns.command, ns.debug, ns.sub.recursive, ns.sub.paths), ("rm", True, True, ["f"]))

    def test_sub_double_dash_is_for_subparser(self):
        ns = self.make().parse(["rm", "--", "-r"])
        self.assertEqual((ns.sub.recursive, ns.sub.paths), (False, ["-r"]))

    def test_subparser_errors_propagate(self):
        with self.assertRaises(UsageError):
            self.make().parse(["add"])  # missing name
        with self.assertRaises(UsageError):
            self.make().parse(["add", "a", "b"])

    def test_commands_and_positionals_rejected(self):
        with self.assertRaises(ValueError):
            Parser(positionals=[Positional("x")], commands={"a": Parser()})

    def test_parent_required_option_enforced(self):
        p = Parser(options=[Option("token", required=True)], commands={"go": Parser()})
        with self.assertRaises(UsageError):
            p.parse(["go"])
        self.assertEqual(p.parse(["--token=1", "go"]).command, "go")

    def test_repeatable_parse_no_state(self):
        p = self.make()
        first = p.parse(["add", "a"])
        second = p.parse(["rm", "b"])
        self.assertEqual((first.command, second.command), ("add", "rm"))
        self.assertEqual(p.parse(["add", "c"]).sub.name, "c")


if __name__ == "__main__":
    unittest.main()
