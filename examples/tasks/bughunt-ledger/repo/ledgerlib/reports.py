"""Financial reports built on top of a Ledger."""

from .money import Money


def trial_balance(ledger, as_of=None):
    """Rows ``(code, name, debit, credit)`` in the base currency.

    Accounts with a zero balance are omitted.  The last row is
    ``("", "Total", total_debit, total_credit)``.
    """
    base = ledger.base
    rows = []
    debit_total = Money.zero(base)
    credit_total = Money.zero(base)
    for code in ledger.chart.codes():
        bal = ledger.balance_in(code, base, as_of)
        if bal.is_zero():
            continue
        name = ledger.chart.get(code).name
        if bal.cents > 0:
            rows.append((code, name, bal, Money.zero(base)))
            debit_total = debit_total + bal
        else:
            rows.append((code, name, Money.zero(base), -bal))
            credit_total = credit_total - bal
    rows.append(("", "Total", debit_total, credit_total))
    return rows


def income_statement(ledger, start, end):
    """Dict with ``income``, ``expenses`` and ``net`` Money values for a period.

    Entries dated ``start`` through ``end`` (inclusive) are included, and
    everything is converted to the base currency.
    """
    base = ledger.base
    income = Money.zero(base)
    expenses = Money.zero(base)
    for entry in ledger.journal.between(start, end):
        for line in entry.lines:
            account = ledger.chart.get(line.account)
            converted = ledger.rates.convert(line.amount, base)
            if account.type == "income":
                income = income - converted
            elif account.type == "expense":
                expenses = expenses + converted
    return {"income": income, "expenses": expenses, "net": income - expenses}


def balance_sheet(ledger, as_of=None):
    """Dict with ``assets``, ``liabilities``, ``equity`` (natural sign) in base currency."""
    base = ledger.base
    out = {}
    for kind, label in (("asset", "assets"), ("liability", "liabilities"), ("equity", "equity")):
        total = Money.zero(base)
        for code in ledger.chart.roots():
            if ledger.chart.get(code).type == kind:
                total = total + ledger.rates.convert(ledger.natural_balance(code, as_of, rollup=True), base)
        out[label] = total
    return out


def account_statement(ledger, code, start, end):
    """Running-balance rows ``(date, memo, amount, balance)`` for one account.

    The opening balance (everything dated before ``start``) is the first row
    with memo ``"Opening balance"``.
    """
    cur = ledger.chart.get(code).currency
    running = Money.zero(cur)
    rows = []
    for entry, amount in ledger.history(code):
        if entry.date < start:
            running = running + amount
    rows.append((start, "Opening balance", Money.zero(cur), running))
    for entry, amount in ledger.history(code):
        if start <= entry.date <= end:
            running = running + amount
            rows.append((entry.date, entry.memo, amount, running))
    return rows


def format_tree(ledger, as_of=None):
    """Indented text listing of the chart with rolled-up natural balances."""
    lines = []
    for code, depth in ledger.chart.walk():
        bal = ledger.natural_balance(code, as_of, rollup=True)
        lines.append("%s%s %s  %s" % ("  " * depth, code, ledger.chart.get(code).name, bal.format()))
    return "\n".join(lines)
