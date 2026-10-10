import unittest

from sheetcalc import (CYCLE, DIV0, NAME, SYNTAX, VALUE, Sheet, col_to_index, dump_csv, expand_range, format_value,
                       index_to_col, load_csv, render_grid)
from sheetcalc.parser import parse_formula, unparse


class ColumnTests(unittest.TestCase):
    def test_letters(self):
        self.assertEqual([index_to_col(i) for i in (1, 2, 25, 27, 28, 53)], ["A", "B", "Y", "AA", "AB", "BA"])
        self.assertEqual([col_to_index(c) for c in ("A", "Y", "AA", "AB", "BA")], [1, 25, 27, 28, 53])

    def test_expand(self):
        self.assertEqual(expand_range("A1", "B2"), ["A1", "B1", "A2", "B2"])


class ArithmeticTests(unittest.TestCase):
    def setUp(self):
        self.s = Sheet()

    def val(self, formula):
        self.s.set("Z99", formula)
        return self.s.get("Z99")

    def test_precedence(self):
        self.assertEqual(self.val("=1+2*3"), 7)
        self.assertEqual(self.val("=(1+2)*3"), 9)
        self.assertEqual(self.val("=-2^2"), -4)
        self.assertEqual(self.val("=2^10"), 1024)
        self.assertEqual(self.val("=10-4-3"), 3)
        self.assertEqual(self.val("=7/2"), 3.5)
        self.assertEqual(self.val("=8/2"), 4)

    def test_text_and_compare(self):
        self.assertEqual(self.val('="a"&"b"'), "ab")
        self.assertEqual(self.val("=1<2"), True)
        self.assertEqual(self.val('="A"="a"'), True)

    def test_errors(self):
        self.assertEqual(self.val("=1/0"), DIV0)
        self.assertEqual(self.val("=NOPE(1)"), NAME)
        self.assertEqual(self.val("=1+"), SYNTAX)
        self.assertEqual(self.val('=1+"x"'), VALUE)


class FunctionTests(unittest.TestCase):
    def setUp(self):
        self.s = Sheet()
        self.s.set_many({"A1": "1", "A2": "2", "A3": "x", "A4": "4"})

    def val(self, formula):
        self.s.set("Z99", formula)
        return self.s.get("Z99")

    def test_aggregates(self):
        self.assertEqual(self.val("=SUM(A1:A4)"), 7)
        self.assertEqual(self.val("=AVERAGE(A1:A4)"), 7 / 3)
        self.assertEqual(self.val("=MIN(A1:A4)"), 1)
        self.assertEqual(self.val("=MAX(A1:A4)"), 4)
        self.assertEqual(self.val("=COUNT(A1:A4)"), 3)
        self.assertEqual(self.val("=COUNTA(A1:A5)"), 4)

    def test_misc(self):
        self.assertEqual(self.val("=ROUND(3.14159,2)"), 3.14)
        self.assertEqual(self.val("=ABS(-3)"), 3)
        self.assertEqual(self.val("=MOD(7,3)"), 1)
        self.assertEqual(self.val("=SQRT(16)"), 4)
        self.assertEqual(self.val('=UPPER("ab")&LOWER("CD")'), "ABcd")
        self.assertEqual(self.val("=IF(A1>0,\"pos\",\"neg\")"), "pos")


class SheetTests(unittest.TestCase):
    def test_recalc_direct(self):
        s = Sheet()
        s.set_many({"A1": "1", "B1": "=A1+1"})
        self.assertEqual(s.get("B1"), 2)
        s.set("A1", "10")
        self.assertEqual(s.get("B1"), 11)

    def test_dependencies(self):
        s = Sheet()
        s.set_many({"A1": "1", "A2": "2", "B1": "=A1+A2", "C1": "=B1"})
        self.assertEqual(s.dependencies("B1"), ["A1", "A2"])
        self.assertEqual(s.dependents("B1"), ["C1"])
        self.assertEqual(s.cells(), ["A1", "B1", "C1", "A2"])

    def test_cycles(self):
        s = Sheet()
        s.set_many({"A1": "=A1+1", "B1": "=C1", "C1": "=B1"})
        self.assertEqual((s.get("A1"), s.get("B1"), s.get("C1")), (CYCLE, CYCLE, CYCLE))
        s.set("C1", "5")
        self.assertEqual((s.get("B1"), s.get("C1")), (5, 5))

    def test_copy_relative(self):
        s = Sheet()
        s.set_many({"A1": "1", "B1": "=A1*2"})
        s.copy("B1", "B2")
        self.assertEqual(s.raw("B2"), "=A2*2")
        s.set("C1", "=$A$1+A1")
        s.copy("C1", "D2")
        self.assertEqual(s.raw("D2"), "=$A$1+B2")
        s.copy("A1", "A5")
        self.assertEqual(s.raw("A5"), "1")

    def test_csv_and_format(self):
        s = load_csv('1,2,"=A1+B1"\nx,"a,b",\n')
        self.assertEqual(s.get("C1"), 3)
        self.assertEqual(s.get("B2"), "a,b")
        self.assertEqual(dump_csv(s), '1,2,3\nx,"a,b",\n')
        self.assertEqual(dump_csv(s, formulas=True), '1,2,=A1+B1\nx,"a,b",\n')
        self.assertEqual(format_value(2.0), "2")
        self.assertEqual(format_value(True), "TRUE")
        self.assertEqual(format_value(CYCLE), "#CYCLE!")

    def test_grid(self):
        s = Sheet()
        s.set_many({"A1": "1", "B1": "hello", "A2": "22"})
        self.assertEqual(render_grid(s, "A1", "B2").split("\n")[0], "  A  B")

    def test_unparse(self):
        self.assertEqual(unparse(parse_formula("(1+2)*3")), "(1+2)*3")
        self.assertEqual(unparse(parse_formula("SUM(A1:B2, 3)")), "SUM(A1:B2,3)")


if __name__ == "__main__":
    unittest.main()
