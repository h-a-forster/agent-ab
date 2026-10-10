"""Temporary holds on stock."""

from .errors import ReservationError


class Reservation:
    def __init__(self, res_id, sku, qty, expires_at):
        self.id = res_id
        self.sku = sku
        self.qty = qty
        self.expires_at = expires_at

    def is_active(self, now):
        """A reservation holds stock until the instant it expires: at ``now == expires_at`` it is over."""
        return now < self.expires_at

    def __repr__(self):
        return "Reservation(%s: %s x%d until %s)" % (self.id, self.sku, self.qty, self.expires_at)


class ReservationBook:
    def __init__(self):
        self._items = {}
        self._next = 1

    def reserve(self, sku, qty, expires_at):
        if qty <= 0:
            raise ReservationError("quantity must be positive")
        res = Reservation("R%d" % self._next, sku, qty, expires_at)
        self._next += 1
        self._items[res.id] = res
        return res

    def release(self, res_id):
        try:
            return self._items.pop(res_id)
        except KeyError:
            raise ReservationError("unknown reservation %s" % res_id) from None

    def get(self, res_id):
        try:
            return self._items[res_id]
        except KeyError:
            raise ReservationError("unknown reservation %s" % res_id) from None

    def active(self, now, sku=None):
        out = [r for r in self._items.values() if r.is_active(now) and (sku is None or r.sku == sku)]
        return sorted(out, key=lambda r: r.id)

    def reserved_qty(self, sku, now=None):
        """Units of ``sku`` currently held.  With ``now=None`` every stored reservation counts."""
        if now is None:
            return sum(r.qty for r in self._items.values() if r.sku == sku)
        return sum(r.qty for r in self.active(now, sku))

    def purge(self, now):
        """Forget expired reservations; returns how many were removed."""
        stale = [rid for rid, r in self._items.items() if not r.is_active(now)]
        for rid in stale:
            del self._items[rid]
        return len(stale)

    def __len__(self):
        return len(self._items)
