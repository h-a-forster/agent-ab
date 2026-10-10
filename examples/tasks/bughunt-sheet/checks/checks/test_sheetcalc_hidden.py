import unittest

from sheetcalc import (CYCLE, DIV0, NAME, NUM, REF, SYNTAX, VALUE, CellError, Sheet, SheetError, col_to_index,
                       dump_csv, expand_range, format_value, index_to_col, load_csv, render_grid)
from sheetcalc.parser import (Binary, Call, CellRef, Neg, Num, RangeRef, ShiftError, parse_formula, shift_formula,
                              unparse, walk)
from sheetcalc.refs import normalize_key, parse_ref, shift_ref
from sheetcalc.tokenizer import tokenize
from sheetcalc.functions import round_half_away


def sheet(**cells):
    s = Sheet()
    s.set_many(cells)
    return s


def val(formula, **cells):
    s = sheet(**cells)
    s.set("Z99", formula)
    return s.get("Z99")


class ColumnSymptoms(unittest.TestCase):
    def test_known_letters(self):
        cases = {1: "A", 25: "Y", 26: "Z", 27: "AA", 52: "AZ", 53: "BA", 78: "BZ", 676: "YZ", 702: "ZZ",
                 703: "AAA", 18278: "ZZZ", 16384: "XFD"}
        for index, letters in cases.items():
            self.assertEqual(index_to_col(index), letters, index)

    def test_round_trip(self):
        for i in range(1, 3000):
            self.assertEqual(col_to_index(index_to_col(i)), i)

    def test_range_across_z(self):
        self.assertEqual(expand_range("Y1", "AB1"), ["Y1", "Z1", "AA1", "AB1"])
        self.assertEqual(expand_range("Z1", "AA2"), ["Z1", "AA1", "Z2", "AA2"])
        self.assertEqual(expand_range("AY1", "BA1"), ["AY1", "AZ1", "BA1"])

    def test_sheet_with_columns_beyond_z(self):
        s = sheet(Y1="1", Z1="2", AA1="3", AB1="=SUM(Y1:AA1)", AZ1="=Z1*10")
        self.assertEqual(s.get("AB1"), 6)
        self.assertEqual(s.get("AZ1"), 20)
        self.assertEqual(s.cells(), ["Y1", "Z1", "AA1", "AB1", "AZ1"])
        self.assertEqual(s.dependencies("AB1"), ["Y1", "Z1", "AA1"])

    def test_copy_into_and_across_z(self):
        s = sheet(A1="=A2+1", A2="4")
        s.copy("A1", "Z1")
        s.copy("A1", "AA1")
        s.copy("A1", "AZ1")
        self.assertEqual((s.raw("Z1"), s.raw("AA1"), s.raw("AZ1")), ("=Z2+1", "=AA2+1", "=AZ2+1"))
        s.set("Y1", "=Z1+Z2")
        s.copy("Y1", "AA3")
        self.assertEqual(s.raw("AA3"), "=AB3+AB4")

    def test_grid_and_csv_use_letters(self):
        s = sheet(Y1="1", Z1="2", AA1="3")
        header = render_grid(s, "Y1", "AA1").split("\n")[0].split()
        self.assertEqual(header, ["Y", "Z", "AA"])
        s2 = sheet(AA1="x")
        self.assertEqual(dump_csv(s2).split("\n")[0].count(","), 26)
        s3 = load_csv("a," * 26 + "end")
        self.assertEqual(s3.get("AA1"), "end")
        self.assertEqual(s3.get("Z1"), "a")


class ConcatPrecedenceSymptoms(unittest.TestCase):
    def test_concat_below_addition(self):
        self.assertEqual(val('="a"&1+2'), "a3")
        self.assertEqual(val("=1+2&3+4"), "37")
        self.assertEqual(val("=1&2+3"), "15")
        self.assertEqual(val('="a"&5-2'), "a3")

    def test_concat_below_multiplication(self):
        self.assertEqual(val('="x"&2*3'), "x6")
        self.assertEqual(val('=2*3&"x"'), "6x")
        self.assertEqual(val('="n"&-1+3'), "n2")

    def test_with_references(self):
        self.assertEqual(val('="v"&A1+B1', A1="2", B1="3"), "v5")
        self.assertEqual(val('=A1&B1+1', A1="x", B1="3"), "x4")

    def test_comparison_stays_lowest(self):
        self.assertEqual(val('="a"&"b"="ab"'), True)
        self.assertEqual(val('=1+1&""="2"'), True)

    def test_in_function_arguments(self):
        self.assertEqual(val('=UPPER("a"&1+1)'), "A2")
        self.assertEqual(val('=LEN("ab"&2*5)'), 4)

    def test_tree_shape(self):
        tree = parse_formula('"a"&1+2')
        self.assertEqual(tree.op, "&")
        self.assertEqual(tree.right.op, "+")
        self.assertEqual(unparse(tree), '"a"&1+2')
        self.assertEqual(unparse(parse_formula('("a"&1)+2')), '("a"&1)+2')

    def test_other_precedences_unchanged(self):
        self.assertEqual(val("=2+3*4"), 14)
        self.assertEqual(val("=2^3^2"), 512)
        self.assertEqual(val("=-2^2"), -4)
        self.assertEqual(val("=2^-1"), 0.5)
        self.assertEqual(val("=10-2-3"), 5)
        self.assertEqual(val("=2*3^2"), 18)


class ReversedRangeSymptoms(unittest.TestCase):
    DATA = dict(A1="1", B1="2", A2="3", B2="4")

    def test_expand(self):
        self.assertEqual(expand_range("B2", "A1"), ["A1", "B1", "A2", "B2"])
        self.assertEqual(expand_range("A2", "B1"), ["A1", "B1", "A2", "B2"])
        self.assertEqual(expand_range("B1", "A2"), ["A1", "B1", "A2", "B2"])
        self.assertEqual(expand_range("A3", "A1"), ["A1", "A2", "A3"])
        self.assertEqual(expand_range("C1", "A1"), ["A1", "B1", "C1"])

    def test_functions(self):
        d = self.DATA
        self.assertEqual(val("=SUM(B2:A1)", **d), 10)
        self.assertEqual(val("=SUM(A2:B1)", **d), 10)
        self.assertEqual(val("=AVERAGE(B2:A1)", **d), 2.5)
        self.assertEqual(val("=COUNT(B2:A1)", **d), 4)
        self.assertEqual(val("=MAX(B2:A1)", **d), 4)
        self.assertEqual(val("=MIN(B2:A1)", **d), 1)
        self.assertEqual(val("=COUNTA(B2:A1)", **d), 4)
        self.assertEqual(val("=SUM(A2:A1)", **d), 4)

    def test_dependencies_and_recalc(self):
        s = sheet(**self.DATA)
        s.set("E1", "=SUM(B2:A1)")
        self.assertEqual(s.dependencies("E1"), ["A1", "B1", "A2", "B2"])
        self.assertEqual(s.get("E1"), 10)
        s.set("A1", "5")
        self.assertEqual(s.get("E1"), 14)
        self.assertEqual(s.dependents("A1"), ["E1"])
        s.set("F1", "=E1*2")
        self.assertEqual(s.get("F1"), 28)
        s.set("B2", "0")
        self.assertEqual(s.get("F1"), 20)

    def test_concat_over_reversed_range(self):
        s = sheet(A1="a", A2="b", A3="c")
        s.set("B1", "=CONCAT(A3:A1)")
        self.assertEqual(s.get("B1"), "abc")

    def test_cycle_through_reversed_range(self):
        s2 = sheet(A1="=SUM(B2:A1)")
        self.assertEqual(s2.get("A1"), CYCLE)


class RoundSymptoms(unittest.TestCase):
    def test_halves_away_from_zero(self):
        cases = [("2.5", 3), ("-2.5", -3), ("0.5", 1), ("1.5", 2), ("3.5", 4), ("-0.5", -1), ("-1.5", -2), ("4.5", 5)]
        for text, expected in cases:
            self.assertEqual(val("=ROUND(%s)" % text), expected, text)

    def test_digits(self):
        self.assertEqual(val("=ROUND(0.125,2)"), 0.13)
        self.assertEqual(val("=ROUND(-0.125,2)"), -0.13)
        self.assertEqual(val("=ROUND(2.675,2)"), 2.68)
        self.assertEqual(val("=ROUND(1.005,2)"), 1.01)
        self.assertEqual(val("=ROUND(0.35,1)"), 0.4)
        self.assertEqual(val("=ROUND(3.14159,3)"), 3.142)

    def test_negative_digits(self):
        self.assertEqual(val("=ROUND(1250,-2)"), 1300)
        self.assertEqual(val("=ROUND(-1250,-2)"), -1300)
        self.assertEqual(val("=ROUND(1234.5,-2)"), 1200)
        self.assertEqual(val("=ROUND(15,-1)"), 20)
        self.assertEqual(val("=ROUND(25,-1)"), 30)

    def test_with_references_and_expressions(self):
        self.assertEqual(val("=ROUND(A1/2)", A1="5"), 3)
        self.assertEqual(val("=ROUND(A1*B1,2)", A1="0.5", B1="0.25"), 0.13)
        self.assertEqual(val("=SUM(ROUND(2.5),ROUND(-2.5))"), 0)

    def test_helper(self):
        self.assertEqual(round_half_away(2.5), 3)
        self.assertEqual(round_half_away(-2.5), -3)
        self.assertEqual(round_half_away(0.125, 2), 0.13)
        self.assertEqual(round_half_away(7, 0), 7)

    def test_not_half_values(self):
        self.assertEqual(val("=ROUND(2.4)"), 2)
        self.assertEqual(val("=ROUND(2.6)"), 3)
        self.assertEqual(val("=ROUND(-2.6)"), -3)
        self.assertEqual(val("=ROUND(1.234,1)"), 1.2)


class RecalcSymptoms(unittest.TestCase):
    def test_chain(self):
        s = sheet(A1="1", B1="=A1+1", C1="=B1*2", D1="=C1+10")
        self.assertEqual(s.get("D1"), 14)
        s.set("A1", "5")
        self.assertEqual((s.get("B1"), s.get("C1"), s.get("D1")), (6, 12, 22))

    def test_read_order_does_not_matter(self):
        s = sheet(A1="1", B1="=A1+1", C1="=B1*2", D1="=C1+10")
        s.values()
        s.set("A1", "5")
        self.assertEqual(s.get("D1"), 22)
        self.assertEqual(s.get("C1"), 12)

    def test_through_ranges(self):
        s = sheet(A1="1", A2="2", A3="3", B1="=SUM(A1:A3)", C1="=B1*2", D1="=C1+1")
        self.assertEqual(s.get("D1"), 13)
        s.set("A2", "10")
        self.assertEqual(s.get("B1"), 14)
        self.assertEqual(s.get("D1"), 29)

    def test_replace_formula_with_constant(self):
        s = sheet(A1="1", B1="=A1+1", C1="=B1*2", D1="=C1")
        self.assertEqual(s.get("D1"), 4)
        s.set("B1", "100")
        self.assertEqual(s.get("D1"), 200)
        s.set("A1", "7")
        self.assertEqual(s.get("D1"), 200)

    def test_clear(self):
        s = sheet(A1="1", B1="=A1+1", C1="=B1*2", D1="=C1+10")
        self.assertEqual(s.get("D1"), 14)
        s.clear("B1")
        self.assertEqual(s.get("C1"), 0)
        self.assertEqual(s.get("D1"), 10)

    def test_long_chain(self):
        s = Sheet()
        s.set("A1", "1")
        for row in range(2, 51):
            s.set("A%d" % row, "=A%d+1" % (row - 1))
        self.assertEqual(s.get("A50"), 50)
        s.set("A1", "11")
        self.assertEqual(s.get("A50"), 60)
        self.assertEqual(s.get("A25"), 35)

    def test_diamond(self):
        s = sheet(A1="1", B1="=A1+1", C1="=A1+2", D1="=B1+C1", E1="=D1*2")
        self.assertEqual(s.get("E1"), 10)
        s.set("A1", "2")
        self.assertEqual((s.get("D1"), s.get("E1")), (7, 14))
        self.assertEqual(s.dependents("A1"), ["B1", "C1"])

    def test_formula_text_change_rewires(self):
        s = sheet(A1="1", A2="2", B1="=A1", C1="=B1+1")
        self.assertEqual(s.get("C1"), 2)
        s.set("B1", "=A2")
        self.assertEqual(s.get("C1"), 3)
        s.set("A1", "50")
        self.assertEqual(s.get("C1"), 3)
        s.set("A2", "20")
        self.assertEqual(s.get("C1"), 21)

    def test_errors_clear_when_fixed(self):
        s = sheet(A1="0", B1="=1/A1", C1="=B1+1", D1="=C1*2")
        self.assertEqual(s.get("D1"), DIV0)
        s.set("A1", "4")
        self.assertEqual(s.get("D1"), 2.5)

    def test_copy_triggers_recalc(self):
        s = sheet(A1="1", A2="2", B1="=A1", C1="=B1")
        self.assertEqual(s.get("C1"), 1)
        s.copy("B1", "B2")
        s.set("C2", "=B2+C1")
        self.assertEqual(s.get("C2"), 3)
        s.set("A2", "9")
        self.assertEqual(s.get("C2"), 10)


class IfSymptoms(unittest.TestCase):
    def test_unselected_branch_not_evaluated(self):
        self.assertEqual(val("=IF(TRUE,1,1/0)"), 1)
        self.assertEqual(val("=IF(FALSE,1/0,2)"), 2)
        self.assertEqual(val('=IF(TRUE,"ok",SQRT(-4))'), "ok")
        self.assertEqual(val("=IF(FALSE,NOPE(1),3)"), 3)
        self.assertEqual(val("=IF(TRUE,1,1+)"), SYNTAX)

    def test_guard_division(self):
        self.assertEqual(val("=IF(A1=0,0,10/A1)", A1="0"), 0)
        self.assertEqual(val("=IF(A1=0,0,10/A1)", A1="5"), 2)
        self.assertEqual(val('=IF(A1=0,"n/a",100/A1)', A1="0"), "n/a")
        self.assertEqual(val("=IF(A1>0,10/A1,0)", A1="0"), 0)

    def test_nested(self):
        self.assertEqual(val("=IF(A1=0,0,IF(B1=0,SQRT(-1),1))", A1="0", B1="0"), 0)
        self.assertEqual(val("=IF(A1=0,0,IF(B1=0,SQRT(-1),1))", A1="1", B1="1"), 1)
        self.assertEqual(val("=IF(A1=0,0,IF(B1=0,SQRT(-1),1))", A1="1", B1="0"), NUM)

    def test_two_argument_form(self):
        self.assertEqual(val("=IF(FALSE,1/0)"), False)
        self.assertEqual(val("=IF(TRUE,7)"), 7)

    def test_inside_other_functions(self):
        self.assertEqual(val("=SUM(IF(TRUE,1,1/0),2)"), 3)
        self.assertEqual(val("=ROUND(IF(A1=0,0,1/A1),2)", A1="0"), 0)
        self.assertEqual(val('=IF(A1="",0,LEN(A1))&"x"', A1="abc"), "3x")

    def test_selected_branch_errors_still_propagate(self):
        self.assertEqual(val("=IF(TRUE,1/0,1)"), DIV0)
        self.assertEqual(val("=IF(FALSE,1,SQRT(-1))"), NUM)
        self.assertEqual(val("=IF(1/0,1,2)"), DIV0)

    def test_in_sheet_with_dependencies(self):
        s = sheet(A1="0", B1="=IF(A1=0,0,100/A1)", C1="=B1+1")
        self.assertEqual(s.get("C1"), 1)
        s.set("A1", "4")
        self.assertEqual(s.get("C1"), 26)
        self.assertEqual(s.dependencies("B1"), ["A1"])

    def test_iferror(self):
        self.assertEqual(val('=IFERROR(1/0,"x")'), "x")
        self.assertEqual(val("=IFERROR(5,1/0)"), 5)
        self.assertEqual(val("=IFERROR(A1,0)+1", A1="=1/0"), 1)


class CopySymptoms(unittest.TestCase):
    def test_row_absolute(self):
        s = sheet(B1="=A$1*2")
        s.copy("B1", "B3")
        s.copy("B1", "C3")
        self.assertEqual(s.raw("B3"), "=A$1*2")
        self.assertEqual(s.raw("C3"), "=B$1*2")

    def test_column_absolute(self):
        s = sheet(B1="=$A1*2")
        s.copy("B1", "B3")
        s.copy("B1", "C3")
        self.assertEqual(s.raw("B3"), "=$A3*2")
        self.assertEqual(s.raw("C3"), "=$A3*2")

    def test_both_and_neither(self):
        s = sheet(D4="=$A$1+A1")
        s.copy("D4", "F7")
        self.assertEqual(s.raw("F7"), "=$A$1+C4")
        s.set("E4", "=A1+B2")
        s.copy("E4", "G7")
        self.assertEqual(s.raw("G7"), "=C4+D5")

    def test_ranges(self):
        s = sheet(C1="=SUM($A1:B$2)")
        s.copy("C1", "D3")
        self.assertEqual(s.raw("D3"), "=SUM($A3:C$2)")
        s.set("C5", "=SUM(A$1:A$3)")
        s.copy("C5", "D9")
        self.assertEqual(s.raw("D9"), "=SUM(B$1:B$3)")

    def test_fill_down_values(self):
        s = sheet(A1="10", A2="20", A3="30", A4="40", B1="=A$1+$A2")
        targets = s.fill_down("B1", 3)
        self.assertEqual(targets, ["B2", "B3", "B4"])
        self.assertEqual([s.raw(t) for t in targets], ["=A$1+$A3", "=A$1+$A4", "=A$1+$A5"])
        self.assertEqual([s.get("B%d" % i) for i in (1, 2, 3, 4)], [30, 40, 50, 10 + 0])

    def test_shift_helpers(self):
        ref = parse_ref("$A1")
        self.assertEqual(shift_ref(ref, 5, 5).text(), "$A6")
        self.assertEqual(shift_ref(parse_ref("A$1"), 5, 5).text(), "F$1")
        self.assertEqual(shift_ref(parse_ref("$A$1"), 5, 5).text(), "$A$1")
        self.assertEqual(shift_ref(parse_ref("A1"), 5, 5).text(), "F6")
        self.assertEqual(unparse(shift_formula(parse_formula("A$1+$B2"), 2, 2)), "C$1+$B4")


class TokenParserRegression(unittest.TestCase):
    def test_tokens(self):
        kinds = [(t.kind, t.value) for t in tokenize('SUM(A1:B2, 1.5e2)<>"x""y"')]
        self.assertEqual(kinds, [("FUNC", "SUM"), ("OP", "("), ("REF", "A1"), ("OP", ":"), ("REF", "B2"), ("OP", ","),
                                 ("NUM", 150.0), ("OP", ")"), ("OP", "<>"), ("STR", 'x"y'), ("EOF", None)])
        self.assertEqual([t.kind for t in tokenize("true foo $A$1")][:3], ["NAME", "NAME", "REF"])
        self.assertEqual(tokenize("LOG10(2)")[0].kind, "FUNC")

    def test_tree(self):
        tree = parse_formula("-A1+SUM(B1:B3)*2")
        self.assertIsInstance(tree, Binary)
        self.assertEqual(tree.op, "+")
        self.assertIsInstance(tree.left, Neg)
        self.assertIsInstance(tree.right.left, Call)
        kinds = [type(n).__name__ for n in walk(tree)]
        self.assertIn("RangeRef", kinds)
        self.assertEqual(len([n for n in walk(tree) if isinstance(n, CellRef)]), 1)

    def test_unparse_roundtrip(self):
        for text in ("1+2*3", "(1+2)*3", "2^3^2", "(2^3)^2", "-(1+2)", "-2^2", "(-2)^2", "A1:B2", "SUM(A1,B2:C3)",
                     '"a""b"&1', "1-(2-3)", "1-2-3", "2*(3+4)", "1=2", "(1=2)=FALSE", "$A$1+B$2"):
            tree = parse_formula(text)
            self.assertEqual(parse_formula(unparse(tree)), tree, text)
        self.assertEqual(unparse(parse_formula("(1+2)*3")), "(1+2)*3")
        self.assertEqual(unparse(parse_formula("((1))")), "1")
        self.assertEqual(unparse(parse_formula("1-(2-3)")), "1-(2-3)")
        self.assertEqual(unparse(parse_formula("(2^3)^2")), "(2^3)^2")

    def test_syntax_errors(self):
        s = sheet()
        for text in ("=1+", "=(1", "=1 2", '="abc', "=SUM(1,", "=#", "=1+*2", "=A1:", "=@"):
            s.set("A1", text)
            self.assertEqual(s.get("A1"), SYNTAX, text)


class EvaluationRegression(unittest.TestCase):
    def test_arithmetic_and_coercion(self):
        self.assertEqual(val("=1+2*3-4/2"), 5)
        self.assertEqual(val('="3"+4'), 7)
        self.assertEqual(val("=TRUE+1"), 2)
        self.assertEqual(val("=A1+1"), 1)
        self.assertEqual(val("=A1&B1"), "")
        self.assertEqual(val("=-A1", A1="5"), -5)
        self.assertEqual(val("=+A1", A1="5"), 5)
        self.assertEqual(val("=7/2"), 3.5)
        self.assertEqual(val("=6/3"), 2)
        self.assertIsInstance(val("=6/3"), int)

    def test_errors(self):
        self.assertEqual(val("=1/0"), DIV0)
        self.assertEqual(val('=1+"x"'), VALUE)
        self.assertEqual(val("=FOO()"), NAME)
        self.assertEqual(val("=bar"), NAME)
        self.assertEqual(val("=SQRT(-1)"), NUM)
        self.assertEqual(val("=MOD(1,0)"), DIV0)
        self.assertEqual(val("=0^-1"), DIV0)
        self.assertEqual(val("=(-8)^0.5"), NUM)
        self.assertEqual(val("=A1:B2"), VALUE)
        self.assertEqual(val("=A1+1", A1="=1/0"), DIV0)
        self.assertEqual(val("=SUM(A1:A2)", A1="1", A2="=1/0"), DIV0)
        self.assertEqual(val("=AVERAGE(A1:A2)", A1="x"), DIV0)
        self.assertEqual(val("=SUM(A1,1)", A1="=NOPE()"), NAME)

    def test_comparisons(self):
        self.assertEqual(val('="a"<"B"'), True)
        self.assertEqual(val('="a"="A"'), True)
        self.assertEqual(val("=1<>2"), True)
        self.assertEqual(val('=1<"a"'), True)
        self.assertEqual(val('="a"<TRUE'), True)
        self.assertEqual(val("=A1=0"), True)
        self.assertEqual(val('=A1=""'), True)
        self.assertEqual(val("=2>=2"), True)
        self.assertEqual(val("=2<=1"), False)

    def test_functions(self):
        data = dict(A1="1", A2="2", A3="x", A4="4", A5="TRUE")
        self.assertEqual(val("=SUM(A1:A5)", **data), 7)
        self.assertEqual(val("=SUM(A1:A2,10,A4)", **data), 17)
        self.assertEqual(val("=AVERAGE(A1:A5)", **data), 7 / 3)
        self.assertEqual(val("=COUNT(A1:A5)", **data), 3)
        self.assertEqual(val("=COUNTA(A1:A6)", **data), 5)
        self.assertEqual(val("=MIN(A3:A3)", **data), 0)
        self.assertEqual(val("=MAX(A1:A4,100)", **data), 100)
        self.assertEqual(val("=ABS(-2.5)"), 2.5)
        self.assertEqual(val("=MOD(-7,3)"), 2)
        self.assertEqual(val("=POWER(2,0.5)"), 2 ** 0.5)
        self.assertEqual(val("=SQRT(2)"), 2 ** 0.5)
        self.assertEqual(val('=CONCAT("a",1,TRUE)'), "a1TRUE")
        self.assertEqual(val('=LEN("héllo")'), 5)
        self.assertEqual(val("=AND(TRUE,1,A1)", A1="2"), True)
        self.assertEqual(val("=OR(FALSE,0)"), False)
        self.assertEqual(val("=NOT(0)"), True)
        self.assertEqual(val("=ROUND(2.5,2,3)"), VALUE)
        self.assertEqual(val("=ABS()"), VALUE)

    def test_cycles(self):
        s = sheet(A1="=A1+1", B1="=C1", C1="=B1", D1="=A1+1")
        for cell in ("A1", "B1", "C1", "D1"):
            self.assertEqual(s.get(cell), CYCLE, cell)
        s.set("C1", "5")
        self.assertEqual((s.get("B1"), s.get("C1")), (5, 5))
        s.set("A1", "1")
        self.assertEqual(s.get("D1"), 2)

    def test_literals_in_cells(self):
        s = sheet(A1="12", A2="1.5", A3="true", A4="hello", A5=" 7 ", A6="1e3", A7="nan", A8="-4", A9="12abc", A10="3.")
        self.assertEqual([s.get("A%d" % i) for i in range(1, 11)],
                         [12, 1.5, True, "hello", 7, 1000.0, "nan", -4, "12abc", 3.0])
        self.assertEqual(s.raw("A5"), " 7 ")


class SheetRegression(unittest.TestCase):
    def test_names_and_api(self):
        s = Sheet()
        s.set("b2", "5")
        s.set("$C$3", "=B2")
        self.assertEqual(s.get("B2"), 5)
        self.assertEqual(s.get("c3"), 5)
        self.assertEqual(s.raw("B2"), "5")
        self.assertEqual(s.raw("Z9"), "")
        self.assertIsNone(s.get("Z9"))
        self.assertEqual(s.cells(), ["B2", "C3"])
        self.assertEqual(s.values(), {"B2": 5, "C3": 5})
        for bad in ("", "1A", "A", "A0", "AAAA1", "A1:B2", "XFE1"):
            with self.assertRaises(SheetError, msg=bad):
                s.get(bad)
        s.set("B2", None)
        self.assertEqual(s.cells(), ["C3"])

    def test_cells_order_row_major(self):
        s = sheet(B1="1", A2="2", A1="3", C1="4", A3="5")
        self.assertEqual(s.cells(), ["A1", "B1", "C1", "A2", "A3"])

    def test_dependencies_dependents(self):
        s = sheet(A1="1", B1="=A1+A1", C1="=SUM(A1:B1)+B1", D1="=C1")
        self.assertEqual(s.dependencies("B1"), ["A1"])
        self.assertEqual(s.dependencies("C1"), ["A1", "B1"])
        self.assertEqual(s.dependents("A1"), ["B1", "C1"])
        self.assertEqual(s.dependents("D1"), [])
        s.set("C1", "7")
        self.assertEqual(s.dependencies("C1"), [])
        self.assertEqual(s.dependents("A1"), ["B1"])

    def test_copy_plain_and_errors(self):
        s = sheet(A1="hello", B1="=A1&\"!\"", C1="=SUM(A1:B1)")
        s.copy("A1", "A9")
        self.assertEqual(s.raw("A9"), "hello")
        s.copy("B1", "B2")
        self.assertEqual(s.raw("B2"), '=A2&"!"')
        s.copy("C1", "C2")
        self.assertEqual(s.raw("C2"), "=SUM(A2:B2)")
        s.set("B3", "=A1")
        s.copy("B3", "A1")
        self.assertEqual(s.raw("A1"), "=#REF!")
        self.assertEqual(s.get("A1"), REF)
        s.copy("Z50", "A50")
        self.assertEqual(s.raw("A50"), "")

    def test_value_cache_is_consistent(self):
        s = sheet(A1="2", B1="=A1^2")
        self.assertEqual(s.get("B1"), 4)
        self.assertEqual(s.get("B1"), 4)
        self.assertEqual(s.values(), {"A1": 2, "B1": 4})


class CsvFormatRegression(unittest.TestCase):
    def test_load_and_dump(self):
        s = load_csv('1,2,"=A1+B1"\nx,"a,b",\n\n"q""r",,5\n')
        self.assertEqual(s.get("C1"), 3)
        self.assertEqual(s.get("B2"), "a,b")
        self.assertEqual(s.get("A4"), 'q"r')
        self.assertEqual(s.get("C4"), 5)
        self.assertEqual(dump_csv(s), '1,2,3\nx,"a,b",\n,,\n"q""r",,5\n')
        self.assertEqual(dump_csv(s, formulas=True).split("\n")[0], "1,2,=A1+B1")
        self.assertEqual(dump_csv(Sheet()), "")

    def test_origin(self):
        s = load_csv("a,b\nc,d", origin="C2")
        self.assertEqual((s.get("C2"), s.get("D3")), ("a", "d"))
        self.assertEqual(s.cells(), ["C2", "D2", "C3", "D3"])

    def test_format_value(self):
        self.assertEqual(format_value(None), "")
        self.assertEqual(format_value(3), "3")
        self.assertEqual(format_value(3.0), "3")
        self.assertEqual(format_value(0.1 + 0.2), "0.3")
        self.assertEqual(format_value(1 / 3), "0.3333333333")
        self.assertEqual(format_value(False), "FALSE")
        self.assertEqual(format_value("txt"), "txt")
        self.assertEqual(format_value(DIV0), "#DIV/0!")
        self.assertEqual(format_value(float("inf")), "#NUM!")
        self.assertEqual(CellError("#X"), CellError("#X"))
        self.assertEqual(len({DIV0, CellError("#DIV/0!")}), 1)

    def test_grid(self):
        s = sheet(A1="1", B1="hello", A2="22", B2="=A1+A2")
        lines = render_grid(s, "A1", "B2").split("\n")
        self.assertEqual(lines, ["  A  B", "1  1 hello", "2 22    23"])

    def test_ref_helpers(self):
        self.assertEqual(normalize_key("$b$3"), "B3")
        ref = parse_ref("$B3")
        self.assertEqual((ref.col, ref.row, ref.col_abs, ref.row_abs), (2, 3, True, False))
        self.assertEqual(ref.key, "B3")
        self.assertEqual(ref.text(), "$B3")
        self.assertIsNone(shift_ref(parse_ref("A1"), -1, 0))
        with self.assertRaises(ShiftError):
            shift_formula(parse_formula("A1"), 0, -1)


if __name__ == "__main__":
    unittest.main()
