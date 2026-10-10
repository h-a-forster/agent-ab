"""Very small demand forecasting helpers."""

import math


def daily_demand(history, days):
    """Average units per day over the last ``days`` days of ``history``
    (a list of ``(day, units)``); days without sales count as zero."""
    if days < 1:
        raise ValueError("days must be at least 1")
    if not history:
        return 0.0
    last = max(day for day, _ in history)
    first = last - days + 1
    total = sum(units for day, units in history if first <= day <= last)
    return total / days


def days_of_cover(on_hand, demand_per_day):
    """How many whole days the stock lasts (``None`` when there is no demand)."""
    if demand_per_day <= 0:
        return None
    return int(on_hand // demand_per_day)


def suggest_order_qty(on_hand, demand_per_day, lead_time_days, safety_days=0, lot_size=1):
    """Units to order so stock covers lead time plus safety days, rounded up to ``lot_size``."""
    if lot_size < 1:
        raise ValueError("lot_size must be at least 1")
    need = demand_per_day * (lead_time_days + safety_days) - on_hand
    if need <= 0:
        return 0
    units = math.ceil(need)
    return -(-units // lot_size) * lot_size


def demand_from_orders(orders, sku):
    """``[(day, units)]`` for ``sku`` from placed (not cancelled) orders, merged per day."""
    per_day = {}
    for order in orders:
        if order.status != "placed":
            continue
        for line in order.lines:
            if line.sku == sku:
                per_day[order.placed_at] = per_day.get(order.placed_at, 0) + line.qty
    return sorted(per_day.items())
