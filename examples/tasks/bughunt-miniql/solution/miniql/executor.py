"""Query execution: WHERE, GROUP BY, HAVING, projection, DISTINCT, ORDER BY, LIMIT."""

from . import ast
from .errors import ExecError
from .expr import GroupContext, RowContext, evaluate, truth, unparse
from .parser import parse
from .values import sort_key


def run_sql(db, sql):
    return execute(db, parse(sql))


def execute(db, select):
    table = db.table(select.table)
    rows = table.rows()
    if select.where is not None:
        rows = [r for r in rows if truth(evaluate(select.where, RowContext(r))) is True]

    grouped = bool(select.group_by) or _uses_aggregates(select)
    if grouped:
        contexts = _group(select, rows)
        if select.having is not None:
            contexts = [c for c in contexts if truth(evaluate(select.having, c)) is True]
    else:
        if select.having is not None:
            raise ExecError("HAVING needs GROUP BY or an aggregate")
        contexts = [RowContext(r) for r in rows]

    names = _output_names(select, table)
    produced = []  # (output row, context carrying aliases)
    for ctx in contexts:
        out = _project(select, ctx, names, table)
        produced.append((out, ctx.with_aliases(out, alias_first=True)))

    if select.distinct:
        seen = set()
        unique = []
        for out, ctx in produced:
            key = tuple(sort_key(out[n]) for n in names)
            if key not in seen:
                seen.add(key)
                unique.append((out, ctx))
        produced = unique

    if select.order_by:
        produced = _order(select.order_by, produced)

    result = [out for out, _ in produced]
    offset = select.offset or 0
    if select.limit is not None:
        result = result[offset:offset + select.limit]
    else:
        result = result[offset:]
    return result


def _uses_aggregates(select):
    nodes = [item.expr for item in select.items]
    if select.having is not None:
        nodes.append(select.having)
    nodes.extend(o.expr for o in select.order_by)
    return any(ast.contains_aggregate(n) for n in nodes)


def _group(select, rows):
    if not select.group_by:
        return [GroupContext(list(rows))]
    groups = {}
    for row in rows:
        key = tuple(sort_key(evaluate(g, RowContext(row))) for g in select.group_by)
        groups.setdefault(key, []).append(row)
    return [GroupContext(members) for members in groups.values()]


def _output_names(select, table):
    names = []
    for item in select.items:
        if isinstance(item.expr, ast.Star):
            names.extend(table.columns)
        else:
            names.append(item.alias or unparse(item.expr))
    if len(set(names)) != len(names):
        raise ExecError("duplicate output column names")
    return names


def _project(select, ctx, names, table):
    if len(select.items) == 1 and isinstance(select.items[0].expr, ast.Star):
        return dict(ctx.row)
    out = {}
    position = 0
    for item in select.items:
        if isinstance(item.expr, ast.Star):
            for column in table.columns:
                out[names[position]] = ctx.row.get(column)
                position += 1
        else:
            out[names[position]] = evaluate(item.expr, ctx)
            position += 1
    return out


def _order(order_by, produced):
    """Sort stably by each ORDER BY key, applying the last key first."""
    keyed = list(produced)
    for item in reversed(order_by):
        keyed.sort(key=lambda pair, item=item: sort_key(evaluate(item.expr, pair[1])), reverse=item.descending)
    return keyed
