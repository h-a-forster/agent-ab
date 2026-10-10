import unittest

from miniql import CatalogError, Database, ExecError, ParseError, format_table, parse
from miniql.tokens import tokenize


def make_db():
    db = Database()
    db.create_table("emp", ["id", "name", "dept", "salary", "bonus", "city"])
    rows = [
        (1, "Alice", "eng", 100, 10, "Paris"),
        (2, "Bob", "eng", 90, None, "London"),
        (3, "Carol", "ops", 80, 5, "Paris"),
        (4, "dave", "ops", 75, None, "Berlin"),
        (5, "Eve", "sales", 70, 20, None),
        (6, "Frank", "eng", 95, 7, "London"),
        (7, "Gina", "sales", 60, None, "Paris"),
    ]
    for r in rows:
        db.insert("emp", dict(zip(["id", "name", "dept", "salary", "bonus", "city"], r)))
    return db


def ids(rows):
    return [r["id"] for r in rows]


class TokenTests(unittest.TestCase):
    def test_kinds(self):
        toks = tokenize("select a, 'it''s' <> 1.5")
        self.assertEqual([t.kind for t in toks], ["KEYWORD", "IDENT", "OP", "STRING", "OP", "NUMBER", "EOF"])
        self.assertEqual(toks[3].value, "it's")
        self.assertEqual(toks[5].value, 1.5)

    def test_errors(self):
        with self.assertRaises(ParseError):
            tokenize("select 'oops")
        with self.assertRaises(ParseError):
            tokenize("select #")


class ParserTests(unittest.TestCase):
    def test_parse_shape(self):
        q = parse("SELECT DISTINCT a AS b FROM t WHERE a > 1 ORDER BY a DESC LIMIT 3")
        self.assertTrue(q.distinct)
        self.assertEqual(q.table, "t")
        self.assertEqual(q.limit, 3)
        self.assertTrue(q.order_by[0].descending)

    def test_errors(self):
        for bad in ("SELECT FROM t", "SELECT a", "SELECT a FROM t WHERE", "SELECT a FROM t LIMIT x"):
            with self.assertRaises(ParseError, msg=bad):
                parse(bad)


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()

    def test_where_and_or_separately(self):
        self.assertEqual(ids(self.db.query("SELECT id FROM emp WHERE dept = 'eng' AND salary > 90")), [1, 6])
        self.assertEqual(ids(self.db.query("SELECT id FROM emp WHERE dept = 'sales' OR salary > 95")), [1, 5, 7])
        self.assertEqual(ids(self.db.query("SELECT id FROM emp WHERE (dept = 'sales' OR dept = 'ops') AND salary < 75")), [5, 7])

    def test_select_star(self):
        rows = self.db.query("SELECT * FROM emp WHERE id = 2")
        self.assertEqual(rows, [{"id": 2, "name": "Bob", "dept": "eng", "salary": 90, "bonus": None, "city": "London"}])

    def test_order_asc_desc_unique(self):
        self.assertEqual(ids(self.db.query("SELECT id FROM emp ORDER BY salary")), [7, 5, 4, 3, 2, 6, 1])
        self.assertEqual(ids(self.db.query("SELECT id FROM emp ORDER BY salary DESC")), [1, 6, 2, 3, 4, 5, 7])

    def test_limit(self):
        self.assertEqual(ids(self.db.query("SELECT id FROM emp ORDER BY id LIMIT 3")), [1, 2, 3])
        self.assertEqual(ids(self.db.query("SELECT id FROM emp ORDER BY id OFFSET 5")), [6, 7])

    def test_like_simple(self):
        self.assertEqual(ids(self.db.query("SELECT id FROM emp WHERE name LIKE '%a%'")), [3, 4, 6, 7])
        self.assertEqual(ids(self.db.query("SELECT id FROM emp WHERE name LIKE 'B_b'")), [2])

    def test_in_between(self):
        self.assertEqual(ids(self.db.query("SELECT id FROM emp WHERE dept IN ('ops', 'sales')")), [3, 4, 5, 7])
        self.assertEqual(ids(self.db.query("SELECT id FROM emp WHERE salary BETWEEN 75 AND 90")), [2, 3, 4])

    def test_aggregates(self):
        rows = self.db.query("SELECT dept, COUNT(*) AS n, SUM(salary) AS total FROM emp GROUP BY dept ORDER BY dept")
        self.assertEqual(rows, [{"dept": "eng", "n": 3, "total": 285}, {"dept": "ops", "n": 2, "total": 155},
                                {"dept": "sales", "n": 2, "total": 130}])

    def test_having(self):
        rows = self.db.query("SELECT dept FROM emp GROUP BY dept HAVING COUNT(*) > 2")
        self.assertEqual(rows, [{"dept": "eng"}])

    def test_alias_order(self):
        rows = self.db.query("SELECT dept, SUM(salary) AS total FROM emp GROUP BY dept ORDER BY total DESC")
        self.assertEqual([r["dept"] for r in rows], ["eng", "ops", "sales"])

    def test_distinct(self):
        rows = self.db.query("SELECT DISTINCT dept FROM emp ORDER BY dept")
        self.assertEqual([r["dept"] for r in rows], ["eng", "ops", "sales"])

    def test_null_handling(self):
        self.assertEqual(ids(self.db.query("SELECT id FROM emp WHERE bonus IS NULL")), [2, 4, 7])
        self.assertEqual(ids(self.db.query("SELECT id FROM emp WHERE bonus > 6")), [1, 5, 6])

    def test_case_and_functions(self):
        rows = self.db.query("SELECT UPPER(name) AS n, CASE WHEN salary >= 90 THEN 'hi' ELSE 'lo' END AS band FROM emp WHERE id <= 2")
        self.assertEqual(rows, [{"n": "ALICE", "band": "hi"}, {"n": "BOB", "band": "hi"}])

    def test_errors(self):
        with self.assertRaises(CatalogError):
            self.db.query("SELECT a FROM nope")
        with self.assertRaises(ExecError):
            self.db.query("SELECT nope FROM emp")
        with self.assertRaises(ExecError):
            self.db.query("SELECT id FROM emp WHERE name > 5")

    def test_catalog(self):
        with self.assertRaises(CatalogError):
            self.db.create_table("emp", ["x"])
        with self.assertRaises(CatalogError):
            self.db.insert("emp", {"zzz": 1})
        self.assertEqual(self.db.table_names(), ["emp"])

    def test_format(self):
        text = format_table([{"a": 1, "b": "x"}, {"a": 22, "b": None}])
        self.assertIn("NULL", text)
        self.assertTrue(text.endswith("(2 rows)"))


if __name__ == "__main__":
    unittest.main()
