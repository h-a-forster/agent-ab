import unittest

from miniargs import Option, Parser, Positional, UsageError


def make():
    return Parser(
        options=[
            Option("verbose", short="v", kind="flag"),
            Option("output", short="o"),
            Option("retries", type=int, default=3),
            Option("dry-run", kind="flag"),
        ],
        positionals=[Positional("source"), Positional("extra", required=False)],
    )


class Basics(unittest.TestCase):
    def test_happy_path(self):
        ns = make().parse(["-v", "--output", "o.txt", "in.txt"])
        self.assertEqual((ns.verbose, ns.output, ns.retries, ns.source, ns.extra), (True, "o.txt", 3, "in.txt", None))

    def test_dashes_become_underscores(self):
        self.assertTrue(make().parse(["--dry-run", "x"]).dry_run)

    def test_errors(self):
        p = make()
        for argv in ([], ["--bogus", "x"], ["x", "--output"], ["x", "--retries", "many"], ["a", "b", "c"]):
            with self.assertRaises(UsageError):
                p.parse(argv)

    def test_error_message_names_option(self):
        with self.assertRaises(UsageError) as cm:
            make().parse(["x", "--retries", "many"])
        self.assertIn("--retries", str(cm.exception))

    def test_required_option(self):
        p = Parser(options=[Option("token", required=True)])
        with self.assertRaises(UsageError):
            p.parse([])
        self.assertEqual(p.parse(["--token", "t"]).token, "t")

    def test_many(self):
        p = Parser(positionals=[Positional("files", many=True)])
        self.assertEqual(p.parse(["a", "b"]).files, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
