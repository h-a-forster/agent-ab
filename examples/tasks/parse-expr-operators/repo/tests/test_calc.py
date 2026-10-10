import unittest

from calc import (Binary, EvalError, Num, ParseError, Unary, Var, eval_expr, free_vars,
                  node_count, parse, to_source)


class ParseEval(unittest.TestCase):
    def test_precedence(self):
        self.assertEqual(eval_expr("1 + 2 * 3"), 7)
        self.assertEqual(eval_expr("(1 + 2) * 3"), 9)
        self.assertEqual(eval_expr("10 - 4 - 3"), 3)
        self.assertEqual(eval_expr("-2 * 3"), -6)

    def test_ast(self):
        self.assertEqual(parse("a - 1"), Binary("-", Var("a"), Num(1)))
        self.assertEqual(parse("-x"), Unary("-", Var("x")))

    def test_functions(self):
        self.assertEqual(eval_expr("max(1, 2 + 3, 4)"), 5)
        self.assertEqual(eval_expr("sqrt(16)"), 4)

    def test_errors(self):
        with self.assertRaises(ParseError) as ctx:
            parse("1 +")
        self.assertEqual(ctx.exception.pos, 3)
        with self.assertRaises(ParseError):
            parse("1 $ 2")
        with self.assertRaises(EvalError):
            eval_expr("1 / 0")
        with self.assertRaises(EvalError):
            eval_expr("y + 1")


class PrintAnalyse(unittest.TestCase):
    def test_roundtrip(self):
        for src in ["1 + 2 * 3", "(1 + 2) * 3", "a - (b - c)", "a - b - c", "-(a + b)", "f(1, x * 2)"]:
            self.assertEqual(to_source(parse(src)), src)

    def test_free_vars(self):
        self.assertEqual(free_vars(parse("a + f(b, 2) * -c")), {"a", "b", "c"})

    def test_node_count(self):
        self.assertEqual(node_count(parse("1 + 2 * x")), 5)


if __name__ == "__main__":
    unittest.main()
