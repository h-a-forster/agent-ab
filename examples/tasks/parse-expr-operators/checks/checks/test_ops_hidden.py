import random
import unittest

from calc import (Binary, Call, EvalError, Num, ParseError, Ternary, Unary, Var, eval_expr,
                  free_vars, node_count, parse, to_source)


def ev(text, **env):
    return eval_expr(text, env)


class Precedence(unittest.TestCase):
    def test_power_right_assoc(self):
        self.assertEqual(ev("2 ** 3 ** 2"), 512)
        self.assertEqual(parse("2 ** 3 ** 2"), Binary("**", Num(2), Binary("**", Num(3), Num(2))))

    def test_unary_minus_vs_power(self):
        self.assertEqual(ev("-2 ** 2"), -4)
        self.assertEqual(parse("-2 ** 2"), Unary("-", Binary("**", Num(2), Num(2))))
        self.assertEqual(ev("(-2) ** 2"), 4)

    def test_negative_exponent(self):
        self.assertEqual(ev("2 ** -1"), 0.5)
        self.assertEqual(ev("2 ** -3 ** 2"), 2 ** -9)
        self.assertEqual(parse("2 ** -3 ** 2"),
                         Binary("**", Num(2), Unary("-", Binary("**", Num(3), Num(2)))))

    def test_not_and_power(self):
        self.assertEqual(parse("!a ** 2"), Unary("!", Binary("**", Var("a"), Num(2))))

    def test_mod_same_level_as_mul(self):
        self.assertEqual(ev("10 - 7 % 4 * 2"), 4)
        self.assertEqual(parse("a * b % c"), Binary("%", Binary("*", Var("a"), Var("b")), Var("c")))

    def test_comparison_below_additive(self):
        self.assertEqual(ev("1 + 2 < 2 + 2"), 1)
        self.assertEqual(ev("1 + 2 >= 2 * 2"), 0)

    def test_logic_levels(self):
        self.assertEqual(ev("1 || 0 && 0"), 1)
        self.assertEqual(parse("a || b && c"), Binary("||", Var("a"), Binary("&&", Var("b"), Var("c"))))
        self.assertEqual(ev("1 < 2 && 2 < 3"), 1)
        self.assertEqual(ev("!0 == 1"), 1)
        self.assertEqual(parse("!a == b"), Binary("==", Unary("!", Var("a")), Var("b")))

    def test_ternary_right_assoc(self):
        self.assertEqual(parse("a ? b : c ? d : e"),
                         Ternary(Var("a"), Var("b"), Ternary(Var("c"), Var("d"), Var("e"))))
        self.assertEqual(parse("a ? b ? c : d : e"),
                         Ternary(Var("a"), Ternary(Var("b"), Var("c"), Var("d")), Var("e")))

    def test_ternary_lowest(self):
        self.assertEqual(ev("1 < 2 || 0 ? 10 + 1 : 20"), 11)
        self.assertEqual(ev("x > 5 ? 1 : x > 2 ? 2 : 3", x=3), 2)

    def test_ternary_in_call_and_parens(self):
        self.assertEqual(ev("max(1, 0 ? 5 : 7, 2)"), 7)
        self.assertEqual(ev("(1 ? 2 : 3) + 10"), 12)


class Evaluation(unittest.TestCase):
    def test_modulo_python_semantics(self):
        self.assertEqual(ev("-7 % 3"), 2)
        self.assertEqual(ev("7 % -3"), -2)
        self.assertEqual(ev("7.5 % 2"), 1.5)

    def test_modulo_zero(self):
        with self.assertRaises(EvalError):
            ev("5 % 0")

    def test_power_int_stays_int(self):
        result = ev("2 ** 10")
        self.assertEqual(result, 1024)
        self.assertIsInstance(result, int)
        self.assertEqual(ev("2 ** 100"), 2**100)
        self.assertEqual(ev("2 ** 0.5"), 2**0.5)

    def test_power_errors(self):
        for bad in ("0 ** -1", "(-8) ** 0.5", "0 ** (0 - 2)"):
            with self.assertRaises(EvalError, msg=bad):
                ev(bad)

    def test_comparisons_return_ints(self):
        for text, want in [("1 < 2", 1), ("2 < 2", 0), ("2 <= 2", 1), ("3 > 4", 0), ("4 >= 4", 1),
                           ("1 == 1.0", 1), ("1 != 1", 0), ("1 != 2", 1)]:
            got = ev(text)
            self.assertEqual(got, want, text)
            self.assertIs(type(got), int, text)

    def test_logic_returns_ints(self):
        for text, want in [("5 && 7", 1), ("5 && 0", 0), ("0 || 0", 0), ("0 || 9", 1), ("!5", 0), ("!0", 1)]:
            got = ev(text)
            self.assertEqual(got, want, text)
            self.assertIs(type(got), int, text)

    def test_short_circuit(self):
        self.assertEqual(ev("x != 0 && 10 / x > 1", x=0), 0)
        self.assertEqual(ev("x == 0 || 10 / x > 1", x=0), 1)
        self.assertEqual(ev("1 || nope"), 1)
        self.assertEqual(ev("0 && nope"), 0)

    def test_ternary_lazy(self):
        self.assertEqual(ev("x ? 10 / x : -1", x=0), -1)
        self.assertEqual(ev("x ? 10 / x : -1", x=5), 2)
        self.assertEqual(ev("1 ? 7 : nope"), 7)

    def test_not_operand_errors_still_raise(self):
        with self.assertRaises(EvalError):
            ev("1 && nope")

    def test_existing_still_works(self):
        self.assertEqual(ev("1 + 2 * 3 - 4 / 2"), 5)
        self.assertEqual(ev("-x + +3", x=1), 2)
        with self.assertRaises(EvalError):
            ev("1 / 0")


class Errors(unittest.TestCase):
    def pos(self, text):
        with self.assertRaises(ParseError) as ctx:
            parse(text)
        return ctx.exception.pos

    def test_chained_comparison(self):
        self.assertEqual(self.pos("1 < 2 < 3"), 6)
        self.assertEqual(self.pos("a == b != c"), 7)
        self.assertEqual(self.pos("a <= b >= c"), 7)
        parse("(1 < 2) < 3")

    def test_comparison_inside_logic_is_fine(self):
        parse("a < b && c < d || e == f")

    def test_lone_chars(self):
        self.assertEqual(self.pos("a = b"), 2)
        self.assertEqual(self.pos("a & b"), 2)
        self.assertEqual(self.pos("a | b"), 2)

    def test_incomplete(self):
        self.assertEqual(self.pos("a ? b"), 5)
        self.assertEqual(self.pos("a ? b :"), 7)
        self.assertEqual(self.pos("1 +"), 3)
        self.assertEqual(self.pos("(1"), 2)
        self.assertEqual(self.pos("1 2"), 2)
        self.assertEqual(self.pos("2 **"), 4)

    def test_stray_tokens(self):
        self.assertEqual(self.pos("a : b"), 2)
        self.assertEqual(self.pos("? 1 : 2"), 0)
        self.assertEqual(self.pos("1 ** * 2"), 5)

    def test_greedy_operators(self):
        self.assertEqual(parse("a**b"), Binary("**", Var("a"), Var("b")))
        self.assertEqual(parse("a<=b"), Binary("<=", Var("a"), Var("b")))
        self.assertEqual(parse("a!=b"), Binary("!=", Var("a"), Var("b")))
        self.assertEqual(parse("!!a"), Unary("!", Unary("!", Var("a"))))
        self.assertEqual(parse("a<-b"), Binary("<", Var("a"), Unary("-", Var("b"))))


class Printing(unittest.TestCase):
    CASES = [
        "1 + 2 * 3", "(1 + 2) * 3", "a - b - c", "a - (b - c)", "a / (b * c)", "a * b % c",
        "a * (b % c)", "2 ** 3 ** 2", "(2 ** 3) ** 2", "-a ** 2", "(-a) ** 2", "a ** -b",
        "a ** (b + 1)", "-(a + b)", "-(a * b)", "!(a && b)", "!a && b", "!a ** 2", "(!a) ** 2",
        "a < b && c >= d", "(a < b) == c", "a == (b < c)", "a || b && c", "(a || b) && c",
        "a && (b || c)", "a ? b : c", "a ? b : c ? d : e", "(a ? b : c) ? d : e",
        "a ? b ? c : d : e", "(a ? b : c) + 1", "a + (b ? c : d)",
        "f(a, b ? c : d)", "f()", "a || b ? c && d : e", "(a ? b : c) || d", "a + -b", "--a",
        "x ** 2.5 % 3",
    ]

    def test_exact_text(self):
        for src in self.CASES:
            self.assertEqual(to_source(parse(src)), src, src)

    def test_redundant_parens_removed(self):
        for src, want in [("((a))", "a"), ("(a * b) + c", "a * b + c"), ("a + (b * c)", "a + b * c"),
                          ("(a - b) - c", "a - b - c"), ("a ** (b ** c)", "a ** b ** c"),
                          ("(a ? b : c)", "a ? b : c"), ("a ? (b) : (c ? d : e)", "a ? b : c ? d : e"),
                          ("(-a) * b", "-a * b"), ("-(a ** 2)", "-a ** 2"), ("(a && b) || c", "a && b || c"),
                          ("(a || b) || c", "a || b || c"), ("a || (b || c)", "a || (b || c)"),
                          ("a + 1.50", "a + 1.5")]:
            self.assertEqual(to_source(parse(src)), want, src)

    def test_constructed_trees(self):
        tree = Binary("**", Unary("-", Var("a")), Num(2))
        self.assertEqual(to_source(tree), "(-a) ** 2")
        tree = Ternary(Ternary(Var("a"), Var("b"), Var("c")), Num(1), Num(2))
        self.assertEqual(to_source(tree), "(a ? b : c) ? 1 : 2")
        self.assertEqual(to_source(Call("g", (Num(1), Ternary(Var("a"), Num(2), Num(3))))), "g(1, a ? 2 : 3)")

    def test_random_roundtrip(self):
        rng = random.Random(12345)
        bin_ops = ["+", "-", "*", "/", "%", "**", "<", "<=", ">", ">=", "==", "!=", "&&", "||"]

        def gen(depth):
            if depth == 0 or rng.random() < 0.2:
                return rng.choice([Num(rng.randint(0, 9)), Num(2.5), Var(rng.choice("abc"))])
            kind = rng.random()
            if kind < 0.5:
                return Binary(rng.choice(bin_ops), gen(depth - 1), gen(depth - 1))
            if kind < 0.7:
                return Unary(rng.choice("-+!"), gen(depth - 1))
            if kind < 0.85:
                return Ternary(gen(depth - 1), gen(depth - 1), gen(depth - 1))
            return Call(rng.choice(["f", "g"]), tuple(gen(depth - 1) for _ in range(rng.randint(0, 2))))

        for _ in range(400):
            tree = gen(5)
            text = to_source(tree)
            self.assertEqual(parse(text), tree, text)
            self.assertEqual(to_source(parse(text)), text)


class Analysis(unittest.TestCase):
    def test_free_vars_ternary(self):
        self.assertEqual(free_vars(parse("a ? b + 1 : c ** d")), {"a", "b", "c", "d"})
        self.assertEqual(free_vars(parse("!x && f(y) % 2 < z")), {"x", "y", "z"})
        self.assertEqual(free_vars(parse("1 ? 2 : 3")), set())

    def test_node_count_counts_all_branches(self):
        self.assertEqual(node_count(parse("a ? b : c")), 4)
        self.assertEqual(node_count(parse("a ? b + 1 : -c")), 7)
        self.assertEqual(node_count(parse("!a || b ** 2")), 6)


if __name__ == "__main__":
    unittest.main()
