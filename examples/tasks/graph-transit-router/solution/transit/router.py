"""Earliest-arrival routing (connection scan with transfer times and tie-breaking)."""

import heapq

from .itinerary import Itinerary, Leg


def _scan(tt, origin, depart_at):
    """Label every reachable connection with (legs, trips) and a parent connection index.

    Returns {connection_index: ((legs, trips), parent_index_or_None)}.
    """
    conns = tt.connections
    labels = {}
    best_at = {}  # station -> (label, connection index) over arrivals ready for boarding
    events = []   # (ready_time, seq, station, label, connection index)
    last_on_trip = {}
    seq = 0
    for ci, c in enumerate(conns):
        while events and events[0][0] <= c.dep:
            _, _, st, label, idx = heapq.heappop(events)
            cur = best_at.get(st)
            if cur is None or label < cur[0]:
                best_at[st] = (label, idx)
        options = []
        if c.src == origin and c.dep >= depart_at:
            options.append(((1, (c.trip,)), None))
        prev = last_on_trip.get(c.trip)
        if prev is not None and prev in labels:
            p = conns[prev]
            if p.dst == c.src and p.arr <= c.dep:
                options.append((labels[prev][0], prev))
        got = best_at.get(c.src)
        if got is not None:
            (legs, trips), idx = got
            options.append(((legs + 1, trips + (c.trip,)), idx))
        last_on_trip[c.trip] = ci
        if options:
            label, parent = min(options, key=lambda o: o[0])
            labels[ci] = (label, parent)
            seq += 1
            heapq.heappush(events, (c.arr + tt.transfer_time(c.dst), seq, c.dst, label, ci))
    return labels


def earliest_arrivals(tt, origin, depart_at):
    """Earliest arrival time at every reachable station (the origin maps to ``depart_at``)."""
    out = {origin: depart_at}
    for ci in _scan(tt, origin, depart_at):
        c = tt.connections[ci]
        if c.dst not in out or c.arr < out[c.dst]:
            out[c.dst] = c.arr
    return out


def earliest_arrival(tt, origin, dest, depart_at, max_legs=None):
    """Best itinerary: earliest arrival, then fewest legs, then lexicographically smallest
    sequence of trip ids. ``None`` if ``dest`` cannot be reached (within ``max_legs`` legs)."""
    if origin == dest:
        return Itinerary((), depart_at, depart_at)
    conns = tt.connections
    labels = _scan(tt, origin, depart_at)
    best = None
    for ci, ((legs, trips), _) in labels.items():
        c = conns[ci]
        if c.dst != dest or (max_legs is not None and legs > max_legs):
            continue
        key = (c.arr, legs, trips)
        if best is None or key < best[0]:
            best = (key, ci)
    if best is None:
        return None
    chain = []
    ci = best[1]
    while ci is not None:
        chain.append(ci)
        ci = labels[ci][1]
    chain.reverse()
    legs = []
    for pos, ci in enumerate(chain):
        c = conns[ci]
        if pos == 0 or labels[ci][0][0] != labels[chain[pos - 1]][0][0]:
            legs.append(Leg(c.trip, c.src, c.dst, c.dep, c.arr))
        else:
            legs[-1] = Leg(c.trip, legs[-1].src, c.dst, legs[-1].dep, c.arr)
    return Itinerary(tuple(legs), legs[0].dep, legs[-1].arr)
