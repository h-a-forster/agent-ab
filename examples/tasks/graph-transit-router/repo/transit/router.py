"""Earliest-arrival routing (connection scan)."""

from .itinerary import Itinerary, Leg


def earliest_arrival(tt, origin, dest, depart_at):
    """Itinerary arriving at ``dest`` as early as possible, or None if unreachable."""
    if origin == dest:
        return Itinerary((), depart_at, depart_at)
    reached = {origin: depart_at}
    via = {}  # station -> index of the connection that first reached it at its best time
    on_trip = set()
    for i, c in enumerate(tt.connections):
        if c.trip in on_trip or reached.get(c.src, float("inf")) <= c.dep:
            on_trip.add(c.trip)
            if c.arr < reached.get(c.dst, float("inf")):
                reached[c.dst] = c.arr
                via[c.dst] = i
    if dest not in via:
        return None
    chain = []
    station = dest
    while station != origin:
        i = via[station]
        chain.append(i)
        station = tt.connections[i].src
    chain.reverse()
    legs = []
    for i in chain:
        c = tt.connections[i]
        if legs and legs[-1].trip == c.trip and legs[-1].dst == c.src:
            legs[-1] = Leg(c.trip, legs[-1].src, c.dst, legs[-1].dep, c.arr)
        else:
            legs.append(Leg(c.trip, c.src, c.dst, c.dep, c.arr))
    return Itinerary(tuple(legs), legs[0].dep, legs[-1].arr)
