"""Tables and the database that owns them."""

from .errors import CatalogError


class Table:
    def __init__(self, name, columns):
        if not columns or len(set(columns)) != len(columns):
            raise CatalogError("table %s needs distinct, non-empty columns" % name)
        self.name = name
        self.columns = list(columns)
        self._rows = []

    def insert(self, row):
        unknown = set(row) - set(self.columns)
        if unknown:
            raise CatalogError("unknown column(s) for %s: %s" % (self.name, ", ".join(sorted(unknown))))
        stored = row if set(row) == set(self.columns) else {c: row.get(c) for c in self.columns}
        self._rows.append(stored)
        return stored

    def rows(self):
        """The stored rows (internal dicts; callers must not modify them)."""
        return self._rows

    def __len__(self):
        return len(self._rows)

    def delete_where(self, predicate):
        kept = [r for r in self._rows if not predicate(r)]
        removed = len(self._rows) - len(kept)
        self._rows = kept
        return removed


class Database:
    def __init__(self):
        self._tables = {}

    def create_table(self, name, columns):
        if name in self._tables:
            raise CatalogError("table %s already exists" % name)
        table = Table(name, columns)
        self._tables[name] = table
        return table

    def table(self, name):
        try:
            return self._tables[name]
        except KeyError:
            raise CatalogError("no such table: %s" % name) from None

    def table_names(self):
        return sorted(self._tables)

    def insert(self, name, row):
        return self.table(name).insert(row)

    def insert_many(self, name, rows):
        table = self.table(name)
        for row in rows:
            table.insert(row)
        return len(rows)

    def query(self, sql):
        from .executor import run_sql

        return run_sql(self, sql)

    def query_text(self, sql):
        from .fmt import format_table

        rows = self.query(sql)
        return format_table(rows)
