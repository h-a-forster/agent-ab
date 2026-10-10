import random
import unittest

from transit import Connection, Itinerary, Leg, Timetable, earliest_arrival, earliest_arrivals

C = Connection


def trip_of(it):
    return tuple(l.trip for l in it.legs)


class TransferTimes(unittest.TestCase):
    def tt(self, default=0, **kw):
        return Timetable([
            C("A", "B", 480, 510, "T1"),
            C("B", "C", 515, 560, "T2"),
            C("B", "C", 540, 600, "T3"),
        ], default_transfer=default, **kw)

    def test_equal_is_enough(self):
        it = earliest_arrival(self.tt(default=5), "A", "C", 400)
        self.assertEqual((trip_of(it), it.arrival), (("T1", "T2"), 560))

    def test_one_minute_short_falls_back(self):
        it = earliest_arrival(self.tt(default=6), "A", "C", 400)
        self.assertEqual((trip_of(it), it.arrival), (("T1", "T3"), 600))

    def test_per_station_override(self):
        tt = self.tt(default=0, transfers={"B": 30})
        self.assertEqual(trip_of(earliest_arrival(tt, "A", "C", 400)), ("T1", "T3"))
        tt = self.tt(default=60, transfers={"B": 5})
        self.assertEqual(trip_of(earliest_arrival(tt, "A", "C", 400)), ("T1", "T2"))
        self.assertEqual(tt.transfer_time("B"), 5)
        self.assertEqual(tt.transfer_time("A"), 60)

    def test_unreachable_when_transfer_too_long(self):
        tt = Timetable([C("A", "B", 0, 10, "X"), C("B", "C", 15, 20, "Y")], default_transfer=6)
        self.assertIsNone(earliest_arrival(tt, "A", "C", 0))

    def test_same_trip_needs_no_transfer(self):
        tt = Timetable([C("A", "B", 0, 10, "X"), C("B", "C", 10, 20, "X"), C("C", "D", 22, 30, "X")],
                       default_transfer=100, transfers={"B": 100})
        it = earliest_arrival(tt, "A", "D", 0)
        self.assertEqual(len(it.legs), 1)
        self.assertEqual(it.legs[0], Leg("X", "A", "D", 0, 30))

    def test_origin_boarding_ignores_transfer(self):
        tt = Timetable([C("A", "B", 100, 110, "X")], default_transfer=50, transfers={"A": 50})
        self.assertEqual(earliest_arrival(tt, "A", "B", 100).arrival, 110)

    def test_depart_at_boundary(self):
        tt = Timetable([C("A", "B", 100, 110, "X"), C("A", "B", 200, 210, "Y")])
        self.assertEqual(earliest_arrival(tt, "A", "B", 100).arrival, 110)
        self.assertEqual(earliest_arrival(tt, "A", "B", 101).arrival, 210)
        self.assertIsNone(earliest_arrival(tt, "A", "B", 201))

    def test_returning_to_origin_needs_transfer(self):
        tt = Timetable([
            C("A", "B", 0, 10, "X"), C("B", "A", 10, 20, "Y"), C("A", "C", 22, 30, "Z"),
            C("A", "C", 40, 50, "W"),
        ], default_transfer=5)
        # Z (22) is not reachable via X,Y (arrive A at 20, +5 = 25) but from A at depart_at 0 directly:
        it = earliest_arrival(tt, "A", "C", 0)
        self.assertEqual((trip_of(it), it.arrival), (("Z",), 30))
        # starting at B at time 0? B->A on Y then Z needs 25 > 22 -> W
        it = earliest_arrival(tt, "B", "C", 0)
        self.assertEqual((trip_of(it), it.arrival), (("Y", "W"), 50))

    def test_validation(self):
        for kw in ({"default_transfer": -1}, {"default_transfer": 1.5}, {"transfers": {"A": -2}},
                   {"transfers": {"A": 2.0}}, {"transfers": {"A": True}}):
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):
                    Timetable([], **kw)
        for args in (("A", "B", 1.0, 5, "T"), ("A", "B", 1, True, "T"), ("A", "B", 3, 3, "T"), ("A", "A", 1, 2, "T")):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    C(*args)


class TieBreaks(unittest.TestCase):
    def test_earlier_arrival_beats_fewer_legs(self):
        tt = Timetable([
            C("A", "C", 0, 100, "SLOW"),
            C("A", "B", 0, 10, "F1"), C("B", "D", 10, 20, "F2"), C("D", "C", 20, 30, "F3"),
        ], default_transfer=0)
        it = earliest_arrival(tt, "A", "C", 0)
        self.assertEqual((trip_of(it), it.arrival), (("F1", "F2", "F3"), 30))
        self.assertEqual(it.transfers, 2)

    def test_fewer_legs_on_equal_arrival(self):
        tt = Timetable([
            C("A", "C", 0, 60, "DIRECT"),
            C("A", "B", 0, 20, "AAA"), C("B", "C", 30, 60, "AAB"),
        ])
        self.assertEqual(trip_of(earliest_arrival(tt, "A", "C", 0)), ("DIRECT",))

    def test_smallest_trip_id_on_full_tie(self):
        tt = Timetable([C("A", "C", 0, 60, "T5"), C("A", "C", 5, 60, "T3"), C("A", "C", 1, 60, "T4")])
        self.assertEqual(trip_of(earliest_arrival(tt, "A", "C", 0)), ("T3",))

    def test_string_comparison_of_ids(self):
        tt = Timetable([C("A", "C", 0, 60, "T2"), C("A", "C", 0, 60, "T10")])
        self.assertEqual(trip_of(earliest_arrival(tt, "A", "C", 0)), ("T10",))

    def test_lexicographic_over_sequences(self):
        tt = Timetable([
            C("A", "B", 0, 20, "T1"), C("A", "B", 0, 20, "T2"),
            C("B", "C", 30, 60, "T9"), C("B", "C", 30, 60, "T3"),
        ])
        self.assertEqual(trip_of(earliest_arrival(tt, "A", "C", 0)), ("T1", "T3"))

    def test_lexicographic_respects_feasibility(self):
        tt = Timetable([
            C("A", "B", 0, 25, "T1"), C("A", "B", 0, 15, "T2"),
            C("B", "C", 30, 60, "T3"),
        ], default_transfer=10)
        it = earliest_arrival(tt, "A", "C", 0)
        self.assertEqual(trip_of(it), ("T2", "T3"))
        self.assertEqual(it.legs[0].arr, 15)

    def test_first_leg_id_dominates_later_ones(self):
        tt = Timetable([
            C("A", "B", 0, 10, "B1"), C("B", "C", 20, 50, "Z9"),
            C("A", "D", 0, 10, "A1"), C("D", "C", 20, 50, "Z9"),
        ])
        self.assertEqual(trip_of(earliest_arrival(tt, "A", "C", 0)), ("A1", "Z9"))

    def test_fewest_legs_is_checked_before_ids(self):
        tt = Timetable([
            C("A", "C", 0, 60, "ZZ"),
            C("A", "B", 0, 10, "AA"), C("B", "C", 20, 60, "AB"),
        ])
        self.assertEqual(trip_of(earliest_arrival(tt, "A", "C", 0)), ("ZZ",))


class MaxLegs(unittest.TestCase):
    TT = Timetable([
        C("A", "C", 0, 100, "SLOW"),
        C("A", "B", 0, 10, "F1"), C("B", "D", 10, 20, "F2"), C("D", "C", 20, 30, "F3"),
    ])

    def test_limits(self):
        self.assertEqual(earliest_arrival(self.TT, "A", "C", 0).arrival, 30)
        self.assertEqual(earliest_arrival(self.TT, "A", "C", 0, max_legs=3).arrival, 30)
        self.assertEqual(earliest_arrival(self.TT, "A", "C", 0, max_legs=2).arrival, 100)
        self.assertEqual(earliest_arrival(self.TT, "A", "C", 0, max_legs=1).arrival, 100)

    def test_none_when_impossible(self):
        tt = Timetable([C("A", "B", 0, 10, "X"), C("B", "C", 10, 20, "Y")])
        self.assertIsNone(earliest_arrival(tt, "A", "C", 0, max_legs=1))
        self.assertEqual(earliest_arrival(tt, "A", "C", 0, max_legs=2).arrival, 20)

    def test_prefix_with_fewest_legs_is_used(self):
        # reaching B takes 1 leg (late) or 2 legs (early); the final trip needs the early one
        tt = Timetable([
            C("A", "B", 0, 40, "LATE"),
            C("A", "X", 0, 5, "E1"), C("X", "B", 5, 10, "E2"),
            C("B", "C", 45, 60, "FIN"),
        ], default_transfer=0)
        it = earliest_arrival(tt, "A", "C", 0, max_legs=3)
        self.assertEqual(trip_of(it), ("LATE", "FIN"))
        it = earliest_arrival(tt, "A", "C", 0)
        self.assertEqual(it.arrival, 60)


class Itineraries(unittest.TestCase):
    def test_origin_equals_dest(self):
        tt = Timetable([C("A", "B", 0, 10, "X")])
        for station in ("A", "B", "UNKNOWN"):
            it = earliest_arrival(tt, station, station, 77)
            self.assertEqual((it.legs, it.departure, it.arrival, it.transfers), ((), 77, 77, 0))
        self.assertEqual(it.describe(), "")

    def test_unknown_or_unreachable(self):
        tt = Timetable([C("A", "B", 0, 10, "X")])
        self.assertIsNone(earliest_arrival(tt, "A", "Z", 0))
        self.assertIsNone(earliest_arrival(tt, "Z", "B", 0))
        self.assertIsNone(earliest_arrival(tt, "B", "A", 0))

    def test_legs_and_describe(self):
        tt = Timetable([
            C("A", "B", 480, 510, "T1"), C("B", "C", 510, 540, "T1"),
            C("C", "D", 550, 1500, "T2"), C("D", "E", 1510, 1520, "T3"),
        ], default_transfer=5)
        it = earliest_arrival(tt, "A", "E", 0)
        self.assertEqual(it.legs, (Leg("T1", "A", "C", 480, 540), Leg("T2", "C", "D", 550, 1500), Leg("T3", "D", "E", 1510, 1520)))
        self.assertEqual((it.departure, it.arrival, it.transfers), (480, 1520, 2))
        self.assertEqual(it.describe(), "\n".join([
            "08:00 A -> 09:00 C [T1]",
            "  change at C: 10 min",
            "09:10 C -> 25:00 D [T2]",
            "  change at D: 10 min",
            "25:10 D -> 25:20 E [T3]",
        ]))

    def test_single_leg_describe_has_no_change_line(self):
        tt = Timetable([C("A", "B", 61, 125, "T")])
        self.assertEqual(earliest_arrival(tt, "A", "B", 0).describe(), "01:01 A -> 02:05 B [T]")

    def test_departure_is_first_leg_departure_not_depart_at(self):
        tt = Timetable([C("A", "B", 100, 110, "T")])
        self.assertEqual(earliest_arrival(tt, "A", "B", 0).departure, 100)

    def test_same_trip_two_visits_not_merged_across_transfer(self):
        tt = Timetable([
            C("A", "B", 0, 10, "X"), C("B", "C", 20, 30, "Y"), C("C", "D", 40, 50, "X"),
        ])
        it = earliest_arrival(tt, "A", "D", 0)
        self.assertEqual(trip_of(it), ("X", "Y", "X"))


class Reachability(unittest.TestCase):
    def test_earliest_arrivals(self):
        tt = Timetable([
            C("A", "B", 10, 20, "T1"), C("B", "C", 20, 30, "T1"),
            C("B", "D", 22, 40, "T2"), C("B", "D", 26, 35, "T3"),
            C("A", "E", 0, 5, "T4"),
        ], default_transfer=5)
        got = earliest_arrivals(tt, "A", 8)
        self.assertEqual(got, {"A": 8, "B": 20, "C": 30, "D": 35})

    def test_respects_depart_at_and_unreachable(self):
        tt = Timetable([C("A", "B", 10, 20, "T1")])
        self.assertEqual(earliest_arrivals(tt, "A", 11), {"A": 11})
        self.assertEqual(earliest_arrivals(tt, "Q", 0), {"Q": 0})

    def test_consistent_with_earliest_arrival(self):
        rng = random.Random(5)
        tt = random_timetable(rng)
        table = earliest_arrivals(tt, "S0", 20)
        for st in STATIONS:
            it = earliest_arrival(tt, "S0", st, 20)
            if it is None:
                self.assertNotIn(st, table)
            else:
                self.assertEqual(table[st], it.arrival)


STATIONS = [f"S{i}" for i in range(7)]


def random_timetable(rng, trips=9):
    conns = []
    for t in range(trips):
        trip = f"T{rng.randrange(100):02d}x{t}" if rng.random() < 0.5 else f"T{t}"
        station = rng.choice(STATIONS)
        clock = rng.randrange(0, 120)
        for _ in range(rng.randint(1, 4)):
            nxt = rng.choice([s for s in STATIONS if s != station])
            dur = rng.randint(3, 25)
            conns.append(C(station, nxt, clock, clock + dur, trip))
            station, clock = nxt, clock + dur + rng.randint(0, 6)
    transfers = {s: rng.randint(0, 12) for s in STATIONS if rng.random() < 0.5}
    return Timetable(conns, transfers=transfers, default_transfer=rng.randint(0, 8))


def brute_best(tt, origin, dest, depart_at, max_legs=None):
    """Exhaustive search over all journeys; returns the best (arrival, legs, trips) or None."""
    by_trip = {}
    for c in tt.connections:
        by_trip.setdefault(c.trip, []).append(c)
    best = [None]

    def rides(trip, station, earliest):
        chain = by_trip[trip]
        for i, c in enumerate(chain):
            if c.src == station and c.dep >= earliest:
                j, cur = i, c
                yield cur
                while j + 1 < len(chain) and chain[j + 1].src == cur.dst and chain[j + 1].dep >= cur.arr:
                    j += 1
                    cur = chain[j]
                    yield cur

    def rec(station, arr, prev_trip, trips):
        for trip in by_trip:
            if trip == prev_trip:
                continue
            earliest = depart_at if prev_trip is None else arr + tt.transfer_time(station)
            # a trip may be boarded at several positions; enumerate all boardings
            chain = by_trip[trip]
            for i, c in enumerate(chain):
                if c.src != station or c.dep < earliest:
                    continue
                j, cur = i, c
                while True:
                    new_trips = trips + (trip,)
                    if max_legs is None or len(new_trips) <= max_legs:
                        if cur.dst == dest:
                            key = (cur.arr, len(new_trips), new_trips)
                            if best[0] is None or key < best[0]:
                                best[0] = key
                        rec(cur.dst, cur.arr, trip, new_trips)
                    if j + 1 < len(chain) and chain[j + 1].src == cur.dst and chain[j + 1].dep >= cur.arr:
                        j += 1
                        cur = chain[j]
                    else:
                        break

    rec(origin, depart_at, None, ())
    return best[0]


class Oracle(unittest.TestCase):
    def test_random_timetables_match_exhaustive_search(self):
        rng = random.Random(2024)
        checked = 0
        for case in range(120):
            tt = random_timetable(rng)
            origin, dest = rng.sample(STATIONS, 2)
            depart_at = rng.randrange(0, 80)
            for max_legs in (None, 1, 2):
                want = brute_best(tt, origin, dest, depart_at, max_legs)
                got = earliest_arrival(tt, origin, dest, depart_at, max_legs=max_legs)
                if want is None:
                    self.assertIsNone(got, (case, max_legs))
                else:
                    self.assertIsNotNone(got, (case, max_legs))
                    self.assertEqual((got.arrival, len(got.legs), trip_of(got)), want, (case, max_legs))
                    checked += 1
        self.assertGreater(checked, 60)


class Scale(unittest.TestCase):
    def test_twenty_thousand_connections(self):
        stations = 200
        conns = []
        for k in range(100):
            for i in range(stations - 1):
                dep = k * 7 + i * 10
                conns.append(C(f"S{i:03d}", f"S{i + 1:03d}", dep, dep + 9, f"R{k:03d}"))
        tt = Timetable(conns, default_transfer=1)
        self.assertEqual(len(tt.connections), 19900)
        it = earliest_arrival(tt, "S000", "S199", 0)
        self.assertEqual(it.arrival, 198 * 10 + 9)
        self.assertEqual(len(it.legs), 1)
        reach = earliest_arrivals(tt, "S050", 0)
        self.assertIn("S199", reach)
        self.assertEqual(len(reach), 150)

    def test_many_transfers_chain(self):
        # every hop is its own trip, each needs a transfer
        conns = [C(f"S{i}", f"S{i + 1}", i * 10, i * 10 + 5, f"H{i:05d}") for i in range(3000)]
        tt = Timetable(conns, default_transfer=5)
        it = earliest_arrival(tt, "S0", "S3000", 0)
        self.assertEqual(len(it.legs), 3000)
        self.assertEqual(it.arrival, 2999 * 10 + 5)
        self.assertIsNone(earliest_arrival(tt, "S0", "S3000", 0, max_legs=2999))


if __name__ == "__main__":
    unittest.main()
