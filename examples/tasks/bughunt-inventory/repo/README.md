# warehouse

Catalog, lot-based stock with first-expired-first-out (FEFO) allocation, reservations, line
pricing with quantity tiers and tax, shipping brackets, orders (place / cancel / return), audit
log and stock reports. Money is `Decimal`; quantities are ints; days are ints.

```python
from warehouse import Catalog, Product, Stock, OrderService

catalog = Catalog()
catalog.add(Product("A100", "Widget", "10.00", weight_kg="0.5", tiers=[(10, "5")]))
stock = Stock()
stock.add_lot("L1", "A100", qty=10, received=1, expires=30)
service = OrderService(catalog, stock, tax_rate="0.10")
order = service.place([("A100", 10)], now=5)
order.grand_total          # Decimal('104.50') + shipping
```

Documented behaviour:

* **FEFO**: lots are used in order of earliest expiry; lots that never expire (`expires=None`) are
  used after every lot that does expire; ties by earlier `received`, then lot id. Lots that have
  expired (`expires <= now`) are not usable.
* **Orders** are all-or-nothing and may contain the same SKU on several lines; units promised
  to an earlier line are not available to a later line (never sell more than is there). On
  failure nothing is taken and nothing is logged.
* **Quantity tiers**: buying *at least* `min_qty` units earns the tier's percent (exactly
  `min_qty` qualifies).
* **Rounding**: every money amount (discounts, tax, surcharges, refunds) is rounded to cents
  half away from zero (`0.025` -> `0.03`).
* **Shipping** brackets include their upper limit: 1 kg and below costs 5.00, up to and including
  5 kg 9.50, up to and including 20 kg 18.00; above 20 kg: 18.00 plus 1.20 per started kg.
* **Reservations** hold stock only while active: a reservation with `expires_at = 10` holds stock
  at `now = 9` but not at `now = 10`. `Stock.available(sku, now)` ignores expired reservations
  even if nobody called `purge`.
* **Cancelling** an order returns every unit to the lot it was taken from.

Run the tests with `python -m unittest discover -s tests -t .`.
