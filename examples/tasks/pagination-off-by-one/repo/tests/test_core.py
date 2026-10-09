import unittest

from pagekit import PageOutOfRange, page_numbers, paginate


class PaginateArgumentTests(unittest.TestCase):
    def test_per_page_must_be_positive(self):
        with self.assertRaises(ValueError):
            paginate([1, 2, 3], 1, per_page=0)

    def test_page_zero_is_out_of_range(self):
        with self.assertRaises(PageOutOfRange):
            paginate([1, 2, 3], 0, per_page=2)

    def test_first_page_has_no_prev(self):
        self.assertFalse(paginate([1, 2, 3, 4], 1, per_page=2).has_prev)


class PageNumbersTests(unittest.TestCase):
    def test_window_is_clamped(self):
        self.assertEqual(page_numbers(1, 10), [1, 2, 3])
        self.assertEqual(page_numbers(5, 10), [3, 4, 5, 6, 7])
        self.assertEqual(page_numbers(10, 10), [8, 9, 10])

    def test_no_pages(self):
        self.assertEqual(page_numbers(1, 0), [])


if __name__ == "__main__":
    unittest.main()
