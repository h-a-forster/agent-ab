"""Plain-text documents for an order."""

from .money import fmt


def render_invoice(order, catalog):
    """An invoice: one row per line, then the totals.  Amounts use thousands separators."""
    lines = ["Invoice for order %s" % order.id, ""]
    width = max([len(catalog.get(l.sku).name) for l in order.lines] + [4])
    for line in order.lines:
        name = catalog.get(line.sku).name
        row = "%s  x%-3d %10s" % (name.ljust(width), line.qty, fmt(line.net))
        if line.discount:
            row += "  (-%s)" % fmt(line.discount)
        lines.append(row)
    lines.append("")
    lines.append("%-*s %10s" % (width + 6, "Subtotal", fmt(order.totals["net"])))
    lines.append("%-*s %10s" % (width + 6, "Tax", fmt(order.totals["tax"])))
    lines.append("%-*s %10s" % (width + 6, "Shipping", fmt(order.shipping)))
    lines.append("%-*s %10s" % (width + 6, "Total", fmt(order.grand_total)))
    return "\n".join(lines)


def packing_slip(order):
    """Where to pick each unit: lines ``SKU lot units`` grouped by SKU, lots in pick order."""
    out = ["Packing slip for order %s" % order.id]
    current = None
    for sku, lot_id, units in order.allocations:
        if sku != current:
            out.append(sku)
            current = sku
        out.append("  %s x%d" % (lot_id, units))
    return "\n".join(out)
