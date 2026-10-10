"""Line pricing: quantity tiers and tax."""

from decimal import Decimal

from .money import percent_of, round_cents, to_decimal


class PricedLine:
    def __init__(self, sku, qty, unit_price, gross, discount, net, tax):
        self.sku = sku
        self.qty = qty
        self.unit_price = unit_price
        self.gross = gross
        self.discount = discount
        self.net = net
        self.tax = tax

    @property
    def total(self):
        return self.net + self.tax

    def __repr__(self):
        return "PricedLine(%s x%d net=%s tax=%s)" % (self.sku, self.qty, self.net, self.tax)


def tier_percent(product, qty):
    """Discount percent for buying ``qty``: the tier with the highest ``min_qty`` that ``qty``
    reaches (buying exactly ``min_qty`` units qualifies); 0 when no tier is reached."""
    best = Decimal(0)
    for min_qty, percent in product.tiers:
        if qty >= min_qty:
            best = percent
    return best


def price_line(product, qty, tax_rate):
    """Price ``qty`` units.  Discount and tax are each rounded to cents (half away from zero);
    tax is charged on the discounted net amount, only for taxable products."""
    unit = product.unit_price
    gross = round_cents(unit * qty)
    discount = percent_of(gross, tier_percent(product, qty))
    net = gross - discount
    tax = percent_of(net, to_decimal(tax_rate) * 100) if product.taxable else Decimal("0.00")
    return PricedLine(product.sku, qty, unit, gross, discount, net, tax)


def sum_lines(lines):
    """Totals over priced lines: gross, discount, net, tax, total (all rounded sums)."""
    zero = Decimal("0.00")
    gross = sum((l.gross for l in lines), zero)
    discount = sum((l.discount for l in lines), zero)
    net = sum((l.net for l in lines), zero)
    tax = sum((l.tax for l in lines), zero)
    return {"gross": round_cents(gross), "discount": round_cents(discount), "net": round_cents(net),
            "tax": round_cents(tax), "total": round_cents(net + tax)}
