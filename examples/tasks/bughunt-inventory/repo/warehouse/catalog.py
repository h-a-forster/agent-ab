"""Product catalog."""

from decimal import Decimal

from .errors import UnknownProduct, WarehouseError
from .money import to_decimal


class Product:
    """A sellable item.

    ``tiers`` is a list of ``(min_qty, percent)``: buying at least ``min_qty`` units gives
    ``percent`` percent off the line; the tier with the highest ``min_qty`` that is reached applies.
    """

    def __init__(self, sku, name, unit_price, weight_kg="0", taxable=True, tiers=()):
        self.sku = sku
        self.name = name
        self.unit_price = to_decimal(unit_price)
        self.weight_kg = to_decimal(weight_kg)
        self.taxable = bool(taxable)
        self.tiers = sorted(((int(q), to_decimal(p)) for q, p in tiers), key=lambda t: t[0])
        if self.unit_price < 0 or self.weight_kg < 0:
            raise WarehouseError("price and weight must not be negative")
        for _, percent in self.tiers:
            if not Decimal(0) <= percent <= 100:
                raise WarehouseError("tier percent must be between 0 and 100")

    def __repr__(self):
        return "Product(%s)" % self.sku


class Catalog:
    def __init__(self):
        self._products = {}

    def add(self, product):
        if product.sku in self._products:
            raise WarehouseError("duplicate sku %s" % product.sku)
        self._products[product.sku] = product
        return product

    def get(self, sku):
        try:
            return self._products[sku]
        except KeyError:
            raise UnknownProduct(sku) from None

    def __contains__(self, sku):
        return sku in self._products

    def skus(self):
        return sorted(self._products)
