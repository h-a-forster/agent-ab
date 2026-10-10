# transit

Journey planner core for a regional rail timetable. Times are integer minutes since midnight
(they may exceed 1440 for services running past midnight).

```python
from transit import Connection, Timetable, earliest_arrival

tt = Timetable([
    Connection("A", "B", 480, 510, "T1"),    # 08:00 -> 08:30 on trip T1
    Connection("B", "C", 510, 540, "T1"),    # T1 continues to C
    Connection("B", "C", 520, 545, "T2"),
])
trip = earliest_arrival(tt, "A", "C", depart_at=470)
trip.arrival             # 540
print(trip.describe())
```

* `timetable.py` `Connection(src, dst, dep, arr, trip)` (one vehicle hop) and `Timetable`
* `router.py`    `earliest_arrival(tt, origin, dest, depart_at)` -> `Itinerary` or `None`
* `itinerary.py` `Leg`, `Itinerary` and time formatting

A *leg* is a maximal ride on one trip; consecutive connections of the same trip form one leg.
The current router ignores the time needed to change trains.

Run the tests with `python -m unittest discover -s tests -t .`.
