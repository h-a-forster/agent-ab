"""Manual stock corrections: cycle counts and expiry write-offs."""

from .audit import AuditLog
from .errors import WarehouseError


class Adjustment:
    def __init__(self, lot_id, before, after, reason):
        self.lot_id = lot_id
        self.before = before
        self.after = after
        self.reason = reason

    @property
    def delta(self):
        return self.after - self.before

    def __repr__(self):
        return "Adjustment(%s %+d %s)" % (self.lot_id, self.delta, self.reason)


def apply_count(stock, counts, audit=None):
    """Set lot quantities to the counted values (``{lot_id: counted}``).

    Returns the adjustments for lots whose quantity actually changed, sorted by lot id.
    Unknown lots and negative counts are errors and nothing is changed in that case.
    """
    audit = audit if audit is not None else AuditLog()
    for lot_id, counted in counts.items():
        stock.lot(lot_id)
        if counted < 0:
            raise WarehouseError("counted quantity must not be negative")
    changes = []
    for lot_id in sorted(counts):
        lot = stock.lot(lot_id)
        if lot.qty != counts[lot_id]:
            changes.append(Adjustment(lot_id, lot.qty, counts[lot_id], "count"))
            lot.qty = counts[lot_id]
    for change in changes:
        audit.log("stock_adjusted", lot=change.lot_id, delta=change.delta, reason=change.reason)
    return changes


def write_off_expired(stock, now, audit=None):
    """Remove the remaining units of every lot that has expired by ``now`` (``expires <= now``)."""
    audit = audit if audit is not None else AuditLog()
    changes = []
    for lot_id in stock.snapshot():
        lot = stock.lot(lot_id)
        if lot.qty > 0 and lot.expires is not None and lot.expires <= now:
            changes.append(Adjustment(lot_id, lot.qty, 0, "expired"))
            lot.qty = 0
    for change in changes:
        audit.log("stock_adjusted", lot=change.lot_id, delta=change.delta, reason=change.reason)
    return changes


def shrinkage(adjustments):
    """Total units lost (positive number) over a list of adjustments; gains are ignored."""
    return sum(-a.delta for a in adjustments if a.delta < 0)
