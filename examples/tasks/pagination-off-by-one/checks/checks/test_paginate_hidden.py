import unittest

from pagekit import PageOutOfRange, paginate


class PaginateBehaviour(unittest.TestCase):
    def setUp(self):
        self.items = list(range(1, 11))

    def test_full_pages(self):
        self.assertEqual(paginate(self.items, 1, per_page=3).items, [1, 2, 3])
        self.assertEqual(paginate(self.items, 2, per_page=3).items, [4, 5, 6])
        self.assertEqual(paginate(self.items, 3, per_page=3).items, [7, 8, 9])

    def test_partial_last_page(self):
        page = paginate(self.items, 4, per_page=3)
        self.assertEqual(page.items, [10])
        self.assertEqual(page.total_pages, 4)
        self.assertTrue(page.has_prev)
        self.assertFalse(page.has_next)

    def test_exact_multiple(self):
        page = paginate(self.items, 2, per_page=5)
        self.assertEqual(page.items, [6, 7, 8, 9, 10])
        self.assertEqual(page.total_pages, 2)
        self.assertFalse(page.has_next)
        with self.assertRaises(PageOutOfRange):
            paginate(self.items, 3, per_page=5)

    def test_every_item_appears_exactly_once(self):
        for n in range(0, 23):
            items = list(range(n))
            for per_page in range(1, 8):
                first = paginate(items, 1, per_page=per_page)
                seen = []
                for number in range(1, first.total_pages + 1):
                    seen.extend(paginate(items, number, per_page=per_page).items)
                self.assertEqual(seen, items, (n, per_page))
                expected_pages = max(1, -(-n // per_page))
                self.assertEqual(first.total_pages, expected_pages, (n, per_page))

    def test_empty_sequence_has_one_empty_page(self):
        page = paginate([], 1, per_page=5)
        self.assertEqual(page.items, [])
        self.assertEqual(page.total_pages, 1)
        self.assertEqual(page.total_items, 0)
        self.assertFalse(page.has_prev)
        self.assertFalse(page.has_next)
        with self.assertRaises(PageOutOfRange):
            paginate([], 2, per_page=5)

    def test_single_item_per_page(self):
        page = paginate(["a", "b"], 2, per_page=1)
        self.assertEqual(page.items, ["b"])
        self.assertEqual(page.total_pages, 2)

    def test_has_next_in_middle(self):
        page = paginate(self.items, 2, per_page=3)
        self.assertTrue(page.has_prev)
        self.assertTrue(page.has_next)

    def test_out_of_range(self):
        with self.assertRaises(PageOutOfRange):
            paginate(self.items, 5, per_page=3)
        with self.assertRaises(PageOutOfRange):
            paginate(self.items, -1, per_page=3)

    def test_works_with_tuples_and_strings(self):
        self.assertEqual(paginate(tuple("abcdefg"), 3, per_page=3).items, ["g"])
        self.assertEqual(paginate("abcdefg", 1, per_page=3).items, ["a", "b", "c"])

    def test_per_page_validation_still_applies(self):
        with self.assertRaises(ValueError):
            paginate(self.items, 1, per_page=-2)
