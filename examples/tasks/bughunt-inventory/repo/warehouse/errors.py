"""Exceptions raised by warehouse."""


class WarehouseError(Exception):
    """Base class."""


class UnknownProduct(WarehouseError):
    """A SKU that is not in the catalog."""


class InsufficientStock(WarehouseError):
    """Not enough sellable stock for a line of an order."""

    def __init__(self, sku, wanted, available):
        super().__init__("%s: wanted %d, only %d available" % (sku, wanted, available))
        self.sku = sku
        self.wanted = wanted
        self.available = available


class OrderError(WarehouseError):
    """Invalid order contents or an unknown / already cancelled order."""


class ReservationError(WarehouseError):
    """Unknown reservation id or an invalid reservation request."""
