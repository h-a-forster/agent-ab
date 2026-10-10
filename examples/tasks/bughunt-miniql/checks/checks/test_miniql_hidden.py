import unittest

from miniql import CatalogError, Database, ExecError, ParseError, format_table, parse
from miniql.tokens import tokenize

COLS = ["id", "name", "dept", "salary", "bonus", "city"]
ROWS = [
    (1, "Alice", "eng", 100, 10, "Paris"),
    (2, "Bob", "eng", 90, None, "London"),
    (3, "Carol", "ops", 80, 5, "Paris"),
    (4, "dave", "ops", 80, None, "Berlin"),
    (5, "Eve", "sales", 70, 20, None),
    (6, "Frank", "eng", 90, 7, "London"),
    (7, "Gina", "sales", 70, None, "Paris"),
]


def make_db():
    db = Database()
    db.create_table("emp", COLS)
    for r in ROWS:
        db.insert("emp", dict(zip(COLS, r)))
    return db


def make_files():
    db = Database()
    db.create_table("files", ["id", "name"])
    names = ["a.c", "abc", "a+b", "aab", "50%", "500", "x[1]", "x1", "f(1)", "f1", "Hello", "multi\nline", "a|b", "ab", "q?", "q"]
    for i, n in enumerate(names, 1):
        db.insert("files", {"id": i, "name": n})
    return db


def names(db, sql):
    return [r["name"] for r in db.query(sql)]


class Base(unittest.TestCase):
    def setUp(self):
        self.db = make_db()

    def ids(self, sql):
        return [r["id"] for r in self.db.query(sql)]


class PrecedenceSymptoms(Base):
    def test_and_binds_tighter_than_or(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE dept = 'sales' OR dept = 'eng' AND salary > 90"), [1, 5, 7])

    def test_and_before_or_other_order(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE salary > 95 OR dept = 'ops' AND city = 'Berlin'"), [1, 4])

    def test_three_terms(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE dept = 'eng' OR dept = 'ops' AND salary < 80 OR id = 7"), [1, 2, 6, 7])
        self.assertEqual(self.ids("SELECT id FROM emp WHERE id = 1 AND dept = 'ops' OR id = 2 AND dept = 'eng'"), [2])

    def test_having(self):
        rows = self.db.query("SELECT dept FROM emp GROUP BY dept HAVING COUNT(*) > 2 OR MIN(salary) = 70 AND COUNT(*) = 2")
        self.assertEqual([r["dept"] for r in rows], ["eng", "sales"])

    def test_case_and_order_by_expression(self):
        rows = self.db.query("SELECT id, CASE WHEN dept = 'ops' OR dept = 'sales' AND salary > 100 THEN 'y' ELSE 'n' END AS f FROM emp WHERE id <= 5")
        self.assertEqual([r["f"] for r in rows], ["n", "n", "y", "y", "n"])

    def test_parenthesised_still_works(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE (dept = 'sales' OR dept = 'eng') AND salary > 90"), [1])

    def test_not_binds_tighter(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE NOT dept = 'eng' AND salary > 75"), [3, 4])
        self.assertEqual(self.ids("SELECT id FROM emp WHERE NOT dept = 'eng' OR id = 1"), [1, 3, 4, 5, 7])

    def test_between_and_inside_logic(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE salary BETWEEN 80 AND 90 AND dept = 'ops' OR id = 5"), [3, 4, 5])


class InNullSymptoms(Base):
    def test_not_in_with_null_literal(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE salary NOT IN (100, NULL)"), [])
        self.assertEqual(self.ids("SELECT id FROM emp WHERE dept NOT IN ('eng', NULL)"), [])

    def test_in_with_null_literal(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE salary IN (100, NULL)"), [1])

    def test_not_wrapping_in(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE NOT (salary IN (90, NULL))"), [])
        self.assertEqual(self.ids("SELECT id FROM emp WHERE NOT (salary IN (90, 80))"), [1, 5, 7])

    def test_not_in_with_null_column_in_list(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE 5 NOT IN (bonus, 1)"), [1, 5, 6])
        self.assertEqual(self.ids("SELECT id FROM emp WHERE 5 IN (bonus, 1)"), [3])

    def test_not_in_null_operand(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE city NOT IN ('Paris')"), [2, 4, 6])
        self.assertEqual(self.ids("SELECT id FROM emp WHERE bonus NOT IN (5, 10)"), [5, 6])

    def test_not_in_without_nulls_is_normal(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE salary NOT IN (100, 90)"), [3, 4, 5, 7])

    def test_unknown_stays_unknown_in_case(self):
        rows = self.db.query("SELECT id, CASE WHEN salary NOT IN (1, NULL) THEN 'y' ELSE 'n' END AS f FROM emp WHERE id <= 2")
        self.assertEqual([r["f"] for r in rows], ["n", "n"])


class OrderSymptoms(Base):
    def test_desc_ties_keep_original_order(self):
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY salary DESC"), [1, 2, 6, 3, 4, 5, 7])

    def test_asc_ties(self):
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY salary"), [5, 7, 3, 4, 2, 6, 1])

    def test_two_desc_keys(self):
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY dept DESC, salary DESC"), [5, 7, 3, 4, 1, 2, 6])

    def test_secondary_desc(self):
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY dept, salary DESC"), [1, 2, 6, 3, 4, 5, 7])
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY dept DESC, salary"), [5, 7, 3, 4, 2, 6, 1])

    def test_secondary_key_breaks_ties(self):
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY salary DESC, name"), [1, 2, 6, 3, 4, 5, 7])
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY salary DESC, id DESC"), [1, 6, 2, 4, 3, 7, 5])

    def test_nulls(self):
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY bonus"), [2, 4, 7, 3, 6, 1, 5])
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY bonus DESC"), [5, 1, 6, 3, 2, 4, 7])

    def test_grouped_desc(self):
        rows = self.db.query("SELECT dept, COUNT(*) AS n FROM emp GROUP BY dept ORDER BY n DESC")
        self.assertEqual([r["dept"] for r in rows], ["eng", "ops", "sales"])
        rows = self.db.query("SELECT dept FROM emp GROUP BY dept ORDER BY COUNT(*) DESC")
        self.assertEqual([r["dept"] for r in rows], ["eng", "ops", "sales"])

    def test_distinct_desc(self):
        rows = self.db.query("SELECT DISTINCT dept, salary FROM emp ORDER BY salary DESC")
        self.assertEqual([(r["dept"], r["salary"]) for r in rows],
                         [("eng", 100), ("eng", 90), ("ops", 80), ("sales", 70)])
        rows = self.db.query("SELECT DISTINCT dept FROM emp ORDER BY dept DESC")
        self.assertEqual([r["dept"] for r in rows], ["sales", "ops", "eng"])

    def test_desc_with_limit(self):
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY salary DESC LIMIT 4"), [1, 2, 6, 3])
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY salary DESC LIMIT 2 OFFSET 1"), [2, 6])


class OffsetSymptoms(Base):
    def test_limit_offset(self):
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY id LIMIT 3 OFFSET 2"), [3, 4, 5])
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY id LIMIT 2 OFFSET 5"), [6, 7])
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY id LIMIT 10 OFFSET 5"), [6, 7])
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY id LIMIT 1 OFFSET 6"), [7])

    def test_edges(self):
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY id LIMIT 0"), [])
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY id LIMIT 0 OFFSET 2"), [])
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY id LIMIT 3 OFFSET 7"), [])
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY id LIMIT 3 OFFSET 0"), [1, 2, 3])
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY id OFFSET 6"), [7])
        self.assertEqual(self.ids("SELECT id FROM emp ORDER BY id OFFSET 9"), [])

    def test_distinct_and_group(self):
        rows = self.db.query("SELECT DISTINCT dept FROM emp ORDER BY dept LIMIT 1 OFFSET 1")
        self.assertEqual(rows, [{"dept": "ops"}])
        rows = self.db.query("SELECT dept, COUNT(*) AS n FROM emp GROUP BY dept ORDER BY dept LIMIT 2 OFFSET 1")
        self.assertEqual(rows, [{"dept": "ops", "n": 2}, {"dept": "sales", "n": 2}])

    def test_where_then_page(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE dept = 'eng' ORDER BY id LIMIT 1 OFFSET 1"), [2])


class LikeSymptoms(unittest.TestCase):
    def setUp(self):
        self.db = make_files()

    def test_dot_is_literal(self):
        self.assertEqual(names(self.db, "SELECT name FROM files WHERE name LIKE 'a.c'"), ["a.c"])
        self.assertEqual(names(self.db, "SELECT name FROM files WHERE name LIKE '%.c'"), ["a.c"])

    def test_other_metacharacters(self):
        self.assertEqual(names(self.db, "SELECT name FROM files WHERE name LIKE 'a+b'"), ["a+b"])
        self.assertEqual(names(self.db, "SELECT name FROM files WHERE name LIKE 'x[1]'"), ["x[1]"])
        self.assertEqual(names(self.db, "SELECT name FROM files WHERE name LIKE 'f(1)'"), ["f(1)"])
        self.assertEqual(names(self.db, "SELECT name FROM files WHERE name LIKE 'a|b'"), ["a|b"])
        self.assertEqual(names(self.db, "SELECT name FROM files WHERE name LIKE 'q?'"), ["q?"])

    def test_wildcards_still_work(self):
        self.assertEqual(names(self.db, "SELECT name FROM files WHERE name LIKE 'a_c'"), ["a.c", "abc"])
        self.assertEqual(names(self.db, "SELECT name FROM files WHERE name LIKE '50%'"), ["50%", "500"])
        self.assertEqual(names(self.db, "SELECT name FROM files WHERE name LIKE 'a%b'"), ["a+b", "aab", "a|b", "ab"])
        self.assertEqual(names(self.db, "SELECT name FROM files WHERE name LIKE 'multi%'"), ["multi\nline"])

    def test_not_like(self):
        rows = names(self.db, "SELECT name FROM files WHERE name NOT LIKE '%a%' AND name NOT LIKE 'x%'")
        self.assertEqual(rows, ["50%", "500", "f(1)", "f1", "Hello", "multi\nline", "q?", "q"])
        self.assertEqual(names(self.db, "SELECT name FROM files WHERE name NOT LIKE '%.%' AND name LIKE 'a%'"),
                         ["abc", "a+b", "aab", "a|b", "ab"])

    def test_case_sensitive(self):
        self.assertEqual(names(self.db, "SELECT name FROM files WHERE name LIKE 'hello'"), [])
        self.assertEqual(names(self.db, "SELECT name FROM files WHERE name LIKE 'Hello'"), ["Hello"])


class AliasingSymptoms(Base):
    def test_select_star_rows_are_copies(self):
        rows = self.db.query("SELECT * FROM emp")
        rows[0]["salary"] = 0
        rows[1]["extra"] = 1
        self.assertEqual(self.db.query("SELECT salary FROM emp WHERE id = 1"), [{"salary": 100}])
        self.assertNotIn("extra", self.db.query("SELECT * FROM emp")[1])

    def test_select_star_variants(self):
        for sql in ("SELECT * FROM emp WHERE id = 1", "SELECT * FROM emp ORDER BY id DESC LIMIT 1",
                    "SELECT DISTINCT * FROM emp WHERE id = 1"):
            rows = self.db.query(sql)
            rows[0]["name"] = "HACKED"
        self.assertEqual(self.ids("SELECT id FROM emp WHERE name = 'HACKED'"), [])

    def test_insert_copies_dict(self):
        db = Database()
        db.create_table("t", ["a", "b"])
        row = {"a": 1, "b": 2}
        db.insert("t", row)
        row["a"] = 99
        row["b"] = 98
        self.assertEqual(db.query("SELECT a, b FROM t"), [{"a": 1, "b": 2}])

    def test_insert_many_copies(self):
        db = Database()
        db.create_table("t", ["a", "b"])
        rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        db.insert_many("t", rows)
        rows[0]["a"] = 100
        rows[1].clear()
        self.assertEqual(db.query("SELECT a, b FROM t"), [{"a": 1, "b": 2}, {"a": 3, "b": 4}])

    def test_partial_insert_still_filled(self):
        db = Database()
        db.create_table("t", ["a", "b"])
        db.insert("t", {"a": 1})
        self.assertEqual(db.query("SELECT * FROM t"), [{"a": 1, "b": None}])

    def test_query_result_mutation_after_insert(self):
        db = Database()
        db.create_table("t", ["a", "b"])
        row = {"a": 1, "b": 2}
        db.insert("t", row)
        out = db.query("SELECT * FROM t")
        out[0]["a"] = 5
        self.assertEqual(db.query("SELECT a FROM t"), [{"a": 1}])
        self.assertEqual(row, {"a": 1, "b": 2})


class OrderAliasSymptoms(Base):
    def test_alias_shadows_column(self):
        self.assertEqual(self.ids("SELECT id, salary * -1 AS salary FROM emp ORDER BY salary"), [1, 2, 6, 3, 4, 5, 7])

    def test_alias_shadows_text(self):
        rows = self.db.query("SELECT UPPER(name) AS name FROM emp ORDER BY name")
        self.assertEqual([r["name"] for r in rows], ["ALICE", "BOB", "CAROL", "DAVE", "EVE", "FRANK", "GINA"])
        rows = self.db.query("SELECT UPPER(name) AS name FROM emp ORDER BY name DESC")
        self.assertEqual([r["name"] for r in rows][:2], ["GINA", "FRANK"])

    def test_grouped_alias(self):
        rows = self.db.query("SELECT dept, COUNT(*) AS salary FROM emp GROUP BY dept ORDER BY salary, dept")
        self.assertEqual([r["dept"] for r in rows], ["ops", "sales", "eng"])

    def test_where_still_uses_column(self):
        rows = self.db.query("SELECT salary * 2 AS salary FROM emp WHERE salary > 85 ORDER BY salary")
        self.assertEqual([r["salary"] for r in rows], [180, 180, 200])

    def test_group_by_uses_column(self):
        rows = self.db.query("SELECT dept AS city, COUNT(*) AS n FROM emp GROUP BY city ORDER BY n DESC, city")
        self.assertEqual([(r["city"], r["n"]) for r in rows], [("eng", 3), ("eng", 2), ("ops", 1), ("sales", 1)])

    def test_non_conflicting_alias_and_column_order(self):
        rows = self.db.query("SELECT id, salary + 1 AS s FROM emp ORDER BY s DESC, id DESC")
        self.assertEqual([r["id"] for r in rows], [1, 6, 2, 4, 3, 7, 5])
        rows = self.db.query("SELECT id FROM emp ORDER BY salary DESC, id")
        self.assertEqual([r["id"] for r in rows], [1, 2, 6, 3, 4, 5, 7])


class TokenizerRegression(unittest.TestCase):
    def test_tokens(self):
        toks = tokenize("select a<=b != 3 <> .5")
        self.assertEqual([(t.kind, t.value) for t in toks],
                         [("KEYWORD", "SELECT"), ("IDENT", "a"), ("OP", "<="), ("IDENT", "b"), ("OP", "<>"),
                          ("NUMBER", 3), ("OP", "<>"), ("NUMBER", 0.5), ("EOF", None)])

    def test_keyword_case_and_ident_case(self):
        toks = tokenize("SeLeCt Name FROM t")
        self.assertEqual((toks[0].value, toks[1].value), ("SELECT", "Name"))

    def test_string_escape(self):
        self.assertEqual(tokenize("'a''b'")[0].value, "a'b")
        self.assertEqual(tokenize("''")[0].value, "")

    def test_errors(self):
        for bad in ("'abc", "a @ b", "a ! b"):
            with self.assertRaises(ParseError, msg=bad):
                tokenize(bad)


class ParserRegression(unittest.TestCase):
    def test_full_shape(self):
        q = parse("SELECT a, COUNT(*) AS n FROM t WHERE a > 1 GROUP BY a HAVING n > 1 ORDER BY a DESC, n LIMIT 5 OFFSET 2")
        self.assertEqual((q.table, q.limit, q.offset), ("t", 5, 2))
        self.assertEqual([o.descending for o in q.order_by], [True, False])
        self.assertEqual(len(q.group_by), 1)
        self.assertIsNotNone(q.having)

    def test_arithmetic_precedence(self):
        db = Database()
        db.create_table("t", ["a"])
        db.insert("t", {"a": 1})
        self.assertEqual(db.query("SELECT 2 + 3 * 4 AS x, (2 + 3) * 4 AS y, 10 - 4 - 3 AS z, -2 * 3 AS w FROM t"),
                         [{"x": 14, "y": 20, "z": 3, "w": -6}])

    def test_errors(self):
        for bad in ("", "SELECT", "SELECT a FROM", "SELECT a FROM t WHERE", "SELECT a FROM t LIMIT 1.5",
                    "SELECT a FROM t ORDER", "SELECT a FROM t extra", "SELECT (a FROM t", "SELECT CASE END FROM t",
                    "SELECT a FROM t WHERE a IN ()", "SELECT a FROM t LIMIT"):
            with self.assertRaises(ParseError, msg=bad):
                parse(bad)

    def test_default_names(self):
        db = make_db()
        row = db.query("SELECT salary + 1, COUNT(*) FROM emp")[0]
        self.assertEqual(list(row), ["(salary + 1)", "COUNT(*)"])


class SemanticsRegression(Base):
    def test_comparison_with_null(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE bonus = NULL"), [])
        self.assertEqual(self.ids("SELECT id FROM emp WHERE bonus <> 5"), [1, 5, 6])
        self.assertEqual(self.ids("SELECT id FROM emp WHERE NOT (bonus > 6)"), [3])
        self.assertEqual(self.ids("SELECT id FROM emp WHERE bonus IS NOT NULL"), [1, 3, 5, 6])

    def test_kleene(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE bonus > 6 OR salary = 90"), [1, 2, 5, 6])
        self.assertEqual(self.ids("SELECT id FROM emp WHERE bonus > 100 AND salary = 90"), [])
        self.assertEqual(self.ids("SELECT id FROM emp WHERE NOT (bonus > 6 AND salary = 90)"), [1, 3, 4, 5, 7])

    def test_between(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE salary BETWEEN 80 AND 90"), [2, 3, 4, 6])
        self.assertEqual(self.ids("SELECT id FROM emp WHERE bonus NOT BETWEEN 6 AND 10"), [3, 5])
        self.assertEqual(self.ids("SELECT id FROM emp WHERE salary BETWEEN 90 AND 80"), [])

    def test_in_lists(self):
        self.assertEqual(self.ids("SELECT id FROM emp WHERE city IN ('Paris', 'Berlin')"), [1, 3, 4, 7])
        self.assertEqual(self.ids("SELECT id FROM emp WHERE id IN (1 + 1, 3 * 2)"), [2, 6])

    def test_arithmetic_and_null(self):
        rows = self.db.query("SELECT id, salary + bonus AS t FROM emp WHERE id <= 2")
        self.assertEqual(rows, [{"id": 1, "t": 110}, {"id": 2, "t": None}])
        rows = self.db.query("SELECT 7 / 2 AS a, 8 / 2 AS b, 7 % 3 AS c, 1 / 0 AS d FROM emp LIMIT 1")
        self.assertEqual(rows, [{"a": 3.5, "b": 4, "c": 1, "d": None}])

    def test_string_concat_plus(self):
        rows = self.db.query("SELECT name + '!' AS n FROM emp WHERE id = 1")
        self.assertEqual(rows, [{"n": "Alice!"}])

    def test_type_errors(self):
        for sql in ("SELECT id FROM emp WHERE name > 5", "SELECT name - 1 AS x FROM emp", "SELECT id FROM emp WHERE salary LIKE 'x'",
                    "SELECT id FROM emp WHERE name", "SELECT nope FROM emp", "SELECT SUM(name) FROM emp",
                    "SELECT id FROM emp HAVING id > 1", "SELECT FOO(id) FROM emp", "SELECT UPPER(id) FROM emp",
                    "SELECT id AS x, name AS x FROM emp"):
            with self.assertRaises(ExecError, msg=sql):
                self.db.query(sql)

    def test_functions(self):
        rows = self.db.query("SELECT UPPER(name) AS u, LOWER(name) AS l, LENGTH(name) AS n, TRIM('  hi ') AS t, "
                             "SUBSTR(name, 2, 3) AS s, SUBSTR(name, 3) AS r, ABS(0 - salary) AS a, "
                             "COALESCE(bonus, 0) AS c, ROUND(2.5) AS r1, ROUND(-2.5) AS r2, ROUND(1.255, 2) AS r3 "
                             "FROM emp WHERE id = 2")
        self.assertEqual(rows, [{"u": "BOB", "l": "bob", "n": 3, "t": "hi", "s": "ob", "r": "b", "a": 90,
                                 "c": 0, "r1": 3, "r2": -3, "r3": 1.26}])

    def test_null_function_args(self):
        rows = self.db.query("SELECT UPPER(city) AS u, LENGTH(city) AS l FROM emp WHERE id = 5")
        self.assertEqual(rows, [{"u": None, "l": None}])

    def test_case(self):
        rows = self.db.query("SELECT id, CASE WHEN salary >= 100 THEN 'A' WHEN salary >= 90 THEN 'B' ELSE 'C' END AS g, "
                             "CASE WHEN id = 99 THEN 1 END AS z FROM emp WHERE id <= 3")
        self.assertEqual([(r["g"], r["z"]) for r in rows], [("A", None), ("B", None), ("C", None)])


class AggregateRegression(Base):
    def test_global_aggregates(self):
        row = self.db.query("SELECT COUNT(*) AS n, COUNT(bonus) AS b, COUNT(DISTINCT dept) AS d, SUM(bonus) AS s, "
                            "AVG(bonus) AS a, MIN(name) AS lo, MAX(salary) AS hi FROM emp")[0]
        self.assertEqual(row, {"n": 7, "b": 4, "d": 3, "s": 42, "a": 10.5, "lo": "Alice", "hi": 100})

    def test_empty_input(self):
        row = self.db.query("SELECT COUNT(*) AS n, SUM(salary) AS s, AVG(salary) AS a, MAX(salary) AS m FROM emp WHERE id > 100")
        self.assertEqual(row, [{"n": 0, "s": None, "a": None, "m": None}])
        self.assertEqual(self.db.query("SELECT dept, COUNT(*) AS n FROM emp WHERE id > 100 GROUP BY dept"), [])

    def test_group_by_with_null_key(self):
        rows = self.db.query("SELECT city, COUNT(*) AS n FROM emp GROUP BY city ORDER BY n DESC, city")
        self.assertEqual([(r["city"], r["n"]) for r in rows], [("Paris", 3), ("London", 2), (None, 1), ("Berlin", 1)])

    def test_group_multi(self):
        rows = self.db.query("SELECT dept, city, COUNT(*) AS n FROM emp GROUP BY dept, city ORDER BY dept, city")
        self.assertEqual([(r["dept"], r["city"], r["n"]) for r in rows],
                         [("eng", "London", 2), ("eng", "Paris", 1), ("ops", "Berlin", 1), ("ops", "Paris", 1),
                          ("sales", None, 1), ("sales", "Paris", 1)])

    def test_having_and_where(self):
        rows = self.db.query("SELECT dept, AVG(salary) AS a FROM emp WHERE salary < 100 GROUP BY dept HAVING AVG(salary) >= 80 ORDER BY dept")
        self.assertEqual(rows, [{"dept": "eng", "a": 90.0}, {"dept": "ops", "a": 80.0}])

    def test_expression_of_aggregates(self):
        rows = self.db.query("SELECT dept, MAX(salary) - MIN(salary) AS spread FROM emp GROUP BY dept ORDER BY spread DESC, dept")
        self.assertEqual([(r["dept"], r["spread"]) for r in rows], [("eng", 10), ("ops", 0), ("sales", 0)])

    def test_count_distinct_and_sum_distinct(self):
        rows = self.db.query("SELECT COUNT(DISTINCT salary) AS c, SUM(DISTINCT salary) AS s FROM emp")
        self.assertEqual(rows, [{"c": 4, "s": 340}])

    def test_avg_ignores_nulls(self):
        rows = self.db.query("SELECT dept, AVG(bonus) AS a FROM emp GROUP BY dept ORDER BY dept")
        self.assertEqual(rows, [{"dept": "eng", "a": 8.5}, {"dept": "ops", "a": 5.0}, {"dept": "sales", "a": 20.0}])

    def test_order_by_aggregate_not_selected(self):
        rows = self.db.query("SELECT dept FROM emp GROUP BY dept ORDER BY SUM(salary) DESC")
        self.assertEqual([r["dept"] for r in rows], ["eng", "ops", "sales"])


class DistinctSelectRegression(Base):
    def test_distinct(self):
        rows = self.db.query("SELECT DISTINCT dept, salary FROM emp ORDER BY dept, salary")
        self.assertEqual(len(rows), 4)
        self.assertEqual(len(self.db.query("SELECT DISTINCT city FROM emp")), 4)

    def test_star(self):
        rows = self.db.query("SELECT * FROM emp WHERE id = 5")
        self.assertEqual(rows, [{"id": 5, "name": "Eve", "dept": "sales", "salary": 70, "bonus": 20, "city": None}])
        self.assertEqual(list(rows[0]), COLS)

    def test_star_with_extra(self):
        rows = self.db.query("SELECT salary * 2 AS double, * FROM emp WHERE id = 1")
        self.assertEqual(list(rows[0]), ["double"] + COLS)
        self.assertEqual(rows[0]["double"], 200)

    def test_projection_order(self):
        rows = self.db.query("SELECT name, id FROM emp WHERE id = 1")
        self.assertEqual(list(rows[0]), ["name", "id"])

    def test_order_by_expression_and_unselected(self):
        self.assertEqual([r["name"] for r in self.db.query("SELECT name FROM emp ORDER BY salary - id DESC LIMIT 2")], ["Alice", "Bob"])
        self.assertEqual([r["id"] for r in self.db.query("SELECT id FROM emp WHERE dept = 'ops' ORDER BY name")], [3, 4])

    def test_empty_results(self):
        self.assertEqual(self.db.query("SELECT * FROM emp WHERE id = 0"), [])


class CatalogRegression(unittest.TestCase):
    def test_table_errors(self):
        db = make_db()
        with self.assertRaises(CatalogError):
            db.create_table("emp", ["a"])
        with self.assertRaises(CatalogError):
            db.create_table("bad", [])
        with self.assertRaises(CatalogError):
            db.create_table("bad", ["a", "a"])
        with self.assertRaises(CatalogError):
            db.insert("nope", {"a": 1})
        with self.assertRaises(CatalogError):
            db.insert("emp", {"id": 1, "zzz": 2})
        with self.assertRaises(CatalogError):
            db.query("SELECT a FROM missing")

    def test_names_and_len(self):
        db = make_db()
        db.create_table("alpha", ["x"])
        self.assertEqual(db.table_names(), ["alpha", "emp"])
        self.assertEqual(len(db.table("emp")), 7)
        self.assertEqual(db.insert_many("alpha", [{"x": 1}, {"x": 2}]), 2)
        self.assertEqual(db.table("alpha").delete_where(lambda r: r["x"] == 1), 1)
        self.assertEqual(db.query("SELECT x FROM alpha"), [{"x": 2}])

    def test_missing_columns_become_null(self):
        db = Database()
        db.create_table("t", ["a", "b", "c"])
        db.insert("t", {"b": 5})
        self.assertEqual(db.query("SELECT * FROM t"), [{"a": None, "b": 5, "c": None}])


class FormatRegression(Base):
    def test_format_table(self):
        text = format_table([{"a": 1, "b": "x"}, {"a": 22, "b": None}])
        lines = text.split("\n")
        self.assertEqual(lines[0], " a | b")
        self.assertEqual(lines[1], "---+-----")
        self.assertEqual(lines[2], " 1 | x")
        self.assertEqual(lines[3], "22 | NULL")
        self.assertEqual(lines[4], "(2 rows)")

    def test_values(self):
        text = format_table([{"f": 2.5, "t": True, "u": False}])
        self.assertIn("2.5", text)
        self.assertIn("true", text)
        self.assertTrue(text.endswith("(1 row)"))

    def test_empty(self):
        self.assertEqual(format_table([]), "(no columns)")
        self.assertEqual(format_table([], ["a"]).split("\n")[-1], "(0 rows)")

    def test_query_text(self):
        text = self.db.query_text("SELECT id, name FROM emp WHERE id <= 2")
        self.assertEqual(text.split("\n")[0], "id | name")
        self.assertTrue(text.endswith("(2 rows)"))


if __name__ == "__main__":
    unittest.main()
