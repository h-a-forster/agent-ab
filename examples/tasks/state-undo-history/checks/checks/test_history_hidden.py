import unittest

from editdoc import Delete, Document, History, Insert


def setup(text="", **kw):
    doc = Document(text)
    return doc, History(doc, **kw)


def type_text(h, pos, s):
    for i, ch in enumerate(s):
        h.execute(Insert(pos + i, ch))


class NoOps(unittest.TestCase):
    def test_noop_not_recorded_and_keeps_redo(self):
        doc, h = setup("abc")
        h.execute(Insert(0, "x"))
        h.undo()
        h.execute(Insert(1, ""))
        h.execute(Delete(0, 0))
        self.assertTrue(h.can_redo)
        self.assertFalse(h.can_undo)
        self.assertEqual(doc.text, "abc")

    def test_noop_does_not_break_coalescing(self):
        doc, h = setup()
        h.execute(Insert(0, "a"))
        h.execute(Insert(1, ""))
        h.execute(Insert(1, "b"))
        self.assertEqual(h.undo_depth, 1)

    def test_failed_command(self):
        doc, h = setup("abc")
        h.execute(Insert(3, "d"))
        with self.assertRaises(IndexError):
            h.execute(Delete(2, 5))
        with self.assertRaises(IndexError):
            h.execute(Insert(-1, "z"))
        self.assertEqual(doc.text, "abcd")
        self.assertEqual(h.undo_depth, 1)
        h.execute(Insert(4, "e"))  # still coalesces: failures did not break the run
        self.assertEqual(h.undo_depth, 1)


class InsertCoalescing(unittest.TestCase):
    def test_typing_run_is_one_step(self):
        doc, h = setup()
        type_text(h, 0, "hello")
        self.assertEqual(h.undo_depth, 1)
        h.undo()
        self.assertEqual(doc.text, "")
        h.redo()
        self.assertEqual(doc.text, "hello")

    def test_non_contiguous_breaks(self):
        doc, h = setup()
        h.execute(Insert(0, "ab"))
        h.execute(Insert(0, "c"))
        h.execute(Insert(3, "d"))
        self.assertEqual(h.undo_depth, 3)
        self.assertEqual(doc.text, "cabd")
        h.undo()
        self.assertEqual(doc.text, "cab")

    def test_newline_rules(self):
        doc, h = setup()
        h.execute(Insert(0, "ab"))
        h.execute(Insert(2, "c\nd"))  # new text contains newline: separate
        self.assertEqual(h.undo_depth, 2)
        doc, h = setup()
        h.execute(Insert(0, "ab\n"))
        h.execute(Insert(3, "c"))  # previous ends with newline: separate
        self.assertEqual(h.undo_depth, 2)
        doc, h = setup()
        h.execute(Insert(0, "a\nb"))
        h.execute(Insert(3, "c"))  # previous contains but does not end with newline: merges
        self.assertEqual(h.undo_depth, 1)

    def test_multichar_inserts_merge(self):
        doc, h = setup()
        h.execute(Insert(0, "ab"))
        h.execute(Insert(2, "cde"))
        h.execute(Insert(5, "f"))
        self.assertEqual(h.undo_depth, 1)
        h.undo()
        self.assertEqual(doc.text, "")

    def test_insert_then_delete_never_merge(self):
        doc, h = setup()
        h.execute(Insert(0, "abc"))
        h.execute(Delete(2, 1))
        h.execute(Insert(2, "z"))
        self.assertEqual(h.undo_depth, 3)

    def test_undo_breaks_run(self):
        doc, h = setup()
        type_text(h, 0, "ab")
        h.undo()
        h.execute(Insert(0, "x"))
        h.execute(Insert(1, "y"))
        self.assertEqual(h.undo_depth, 1)
        h.undo()
        self.assertEqual(doc.text, "")
        h.redo()
        h.execute(Insert(2, "z"))  # redo breaks the run
        self.assertEqual(h.undo_depth, 2)

    def test_failed_undo_still_breaks(self):
        doc, h = setup()
        self.assertFalse(h.undo())
        self.assertFalse(h.redo())
        h.execute(Insert(0, "a"))
        self.assertEqual(h.undo_depth, 1)
        h.execute(Insert(1, "b"))
        self.assertEqual(h.undo_depth, 1)
        self.assertFalse(h.redo())
        h.execute(Insert(2, "c"))
        self.assertEqual(h.undo_depth, 2)

    def test_break_coalescing(self):
        doc, h = setup()
        h.execute(Insert(0, "a"))
        h.break_coalescing()
        h.execute(Insert(1, "b"))
        self.assertEqual(h.undo_depth, 2)

    def test_merge_clears_redo(self):
        doc, h = setup()
        h.execute(Insert(0, "a"))
        h.execute(Insert(1, "b"))
        h.undo()
        h.execute(Insert(0, "x"))
        h.execute(Insert(1, "y"))
        self.assertFalse(h.can_redo)


class DeleteCoalescing(unittest.TestCase):
    def test_backspace_run(self):
        doc, h = setup("hello")
        for pos in (4, 3, 2):
            h.execute(Delete(pos, 1))
        self.assertEqual(doc.text, "he")
        self.assertEqual(h.undo_depth, 1)
        h.undo()
        self.assertEqual(doc.text, "hello")
        h.redo()
        self.assertEqual(doc.text, "he")

    def test_forward_delete_run(self):
        doc, h = setup("hello")
        for _ in range(3):
            h.execute(Delete(1, 1))
        self.assertEqual(doc.text, "ho")
        self.assertEqual(h.undo_depth, 1)
        h.undo()
        self.assertEqual(doc.text, "hello")

    def test_multi_length_mixed_directions(self):
        doc, h = setup("0123456789")
        h.execute(Delete(4, 2))   # removes 45 -> 01236789
        h.execute(Delete(2, 2))   # backspace-type: 2+2 == 4 -> removes 23 -> 016789
        h.execute(Delete(2, 1))   # forward: pos 2 == merged pos 2 -> removes 6 -> 01789
        self.assertEqual(doc.text, "01789")
        self.assertEqual(h.undo_depth, 1)
        h.undo()
        self.assertEqual(doc.text, "0123456789")

    def test_gap_breaks(self):
        doc, h = setup("abcdefgh")
        h.execute(Delete(5, 1))
        h.execute(Delete(2, 1))
        self.assertEqual(h.undo_depth, 2)
        h.execute(Delete(2, 1))
        self.assertEqual(h.undo_depth, 2)
        h.undo()
        self.assertEqual(doc.text, "abcdegh")

    def test_not_adjacent_backspace(self):
        doc, h = setup("abcdef")
        h.execute(Delete(4, 1))
        h.execute(Delete(2, 1))  # 2+1 != 4
        self.assertEqual(h.undo_depth, 2)


class Transactions(unittest.TestCase):
    def test_single_step(self):
        doc, h = setup("abc")
        with h.transaction():
            h.execute(Insert(3, "d"))
            h.execute(Insert(4, "e"))
            h.execute(Delete(0, 1))
            self.assertEqual(doc.text, "bcde")
        self.assertEqual(h.undo_depth, 1)
        h.undo()
        self.assertEqual(doc.text, "abc")
        h.redo()
        self.assertEqual(doc.text, "bcde")

    def test_nested_flattened(self):
        doc, h = setup()
        with h.transaction():
            h.execute(Insert(0, "a"))
            with h.transaction():
                h.execute(Insert(1, "b"))
            h.execute(Insert(2, "c"))
        self.assertEqual(h.undo_depth, 1)
        h.undo()
        self.assertEqual(doc.text, "")

    def test_rollback_on_exception(self):
        doc, h = setup("abc")
        h.execute(Insert(3, "!"))
        h.undo()
        with self.assertRaises(ZeroDivisionError):
            with h.transaction():
                h.execute(Insert(0, "x"))
                h.execute(Delete(1, 2))
                1 / 0
        self.assertEqual(doc.text, "abc")
        self.assertEqual(h.undo_depth, 0)
        self.assertTrue(h.can_redo)

    def test_failing_command_inside_rolls_back_all(self):
        doc, h = setup("abc")
        with self.assertRaises(IndexError):
            with h.transaction():
                h.execute(Insert(0, "x"))
                h.execute(Delete(10, 1))
        self.assertEqual(doc.text, "abc")
        self.assertEqual(h.undo_depth, 0)

    def test_inner_exception_caught_by_outer_body_keeps_work(self):
        doc, h = setup()
        with h.transaction():
            h.execute(Insert(0, "a"))
            try:
                with h.transaction():
                    h.execute(Insert(1, "b"))
                    raise KeyError("x")
            except KeyError:
                pass
            h.execute(Insert(2, "c"))
        self.assertEqual(doc.text, "abc")
        self.assertEqual(h.undo_depth, 1)

    def test_inner_exception_escaping_outer_rolls_back_everything(self):
        doc, h = setup()
        with self.assertRaises(KeyError):
            with h.transaction():
                h.execute(Insert(0, "a"))
                with h.transaction():
                    h.execute(Insert(1, "b"))
                    raise KeyError("x")
        self.assertEqual(doc.text, "")
        self.assertEqual(h.undo_depth, 0)

    def test_failed_command_caught_inside_transaction_continues(self):
        doc, h = setup("ab")
        with h.transaction():
            try:
                h.execute(Delete(5, 1))
            except IndexError:
                pass
            h.execute(Insert(2, "c"))
        self.assertEqual(doc.text, "abc")
        self.assertEqual(h.undo_depth, 1)

    def test_empty_transaction_keeps_redo(self):
        doc, h = setup()
        h.execute(Insert(0, "a"))
        h.undo()
        with h.transaction():
            h.execute(Insert(0, ""))
        self.assertTrue(h.can_redo)
        self.assertEqual(h.undo_depth, 0)

    def test_commit_clears_redo(self):
        doc, h = setup()
        h.execute(Insert(0, "a"))
        h.undo()
        with h.transaction():
            h.execute(Insert(0, "b"))
        self.assertFalse(h.can_redo)

    def test_no_merge_with_neighbours(self):
        doc, h = setup()
        h.execute(Insert(0, "a"))
        with h.transaction():
            h.execute(Insert(1, "b"))
        h.execute(Insert(2, "c"))
        self.assertEqual(h.undo_depth, 3)
        doc, h = setup()
        with h.transaction():
            h.execute(Insert(0, "a"))
        h.execute(Insert(1, "b"))
        self.assertEqual(h.undo_depth, 2)

    def test_forbidden_calls_inside(self):
        doc, h = setup()
        h.execute(Insert(0, "a"))
        with h.transaction():
            for fn in (h.undo, h.redo, h.mark_saved):
                with self.assertRaises(RuntimeError):
                    fn()
        self.assertEqual(doc.text, "a")

    def test_usable_after_failed_transaction(self):
        doc, h = setup()
        with self.assertRaises(ValueError):
            with h.transaction():
                h.execute(Insert(0, "a"))
                raise ValueError
        h.execute(Insert(0, "b"))
        self.assertEqual(h.undo_depth, 1)
        h.undo()
        self.assertEqual(doc.text, "")


class Limit(unittest.TestCase):
    def test_validation(self):
        for bad in (0, -1, 1.5, "3"):
            with self.assertRaises(ValueError):
                History(Document(), limit=bad)
        History(Document(), limit=None)

    def test_drops_oldest(self):
        doc, h = setup(limit=2)
        for i, ch in enumerate("abc"):
            h.execute(Insert(i, ch))
            h.break_coalescing()
        self.assertEqual(h.undo_depth, 2)
        h.undo()
        h.undo()
        self.assertFalse(h.undo())
        self.assertEqual(doc.text, "a")

    def test_merged_and_transaction_count_once(self):
        doc, h = setup(limit=2)
        type_text(h, 0, "abcd")
        with h.transaction():
            h.execute(Insert(4, "X"))
            h.execute(Insert(5, "Y"))
        self.assertEqual(h.undo_depth, 2)
        h.undo()
        self.assertEqual(doc.text, "abcd")

    def test_limit_one(self):
        doc, h = setup(limit=1)
        h.execute(Insert(0, "a"))
        h.break_coalescing()
        h.execute(Insert(1, "b"))
        h.undo()
        self.assertEqual(doc.text, "a")
        self.assertFalse(h.can_undo)

    def test_redo_depth(self):
        doc, h = setup()
        h.execute(Insert(0, "a"))
        h.break_coalescing()
        h.execute(Insert(1, "b"))
        h.undo()
        h.undo()
        self.assertEqual((h.undo_depth, h.redo_depth), (0, 2))


class Dirty(unittest.TestCase):
    def test_initial_and_save(self):
        doc, h = setup()
        self.assertFalse(h.is_dirty)
        h.execute(Insert(0, "a"))
        self.assertTrue(h.is_dirty)
        h.mark_saved()
        self.assertFalse(h.is_dirty)

    def test_no_merge_across_save_keeps_saved_point_reachable(self):
        doc, h = setup()
        type_text(h, 0, "ab")
        h.mark_saved()
        h.execute(Insert(2, "c"))
        self.assertEqual(h.undo_depth, 2)
        self.assertTrue(h.is_dirty)
        h.undo()
        self.assertFalse(h.is_dirty)
        self.assertEqual(doc.text, "ab")

    def test_undo_past_save_and_back(self):
        doc, h = setup()
        h.execute(Insert(0, "a"))
        h.break_coalescing()
        h.execute(Insert(1, "b"))
        h.mark_saved()
        h.undo()
        self.assertTrue(h.is_dirty)
        h.undo()
        self.assertTrue(h.is_dirty)
        h.redo()
        h.redo()
        self.assertFalse(h.is_dirty)

    def test_new_command_after_undo_past_save_is_permanently_dirty(self):
        doc, h = setup()
        h.execute(Insert(0, "a"))
        h.break_coalescing()
        h.execute(Insert(1, "b"))
        h.mark_saved()
        h.undo()
        h.undo()
        h.execute(Insert(0, "z"))
        self.assertTrue(h.is_dirty)
        h.undo()
        self.assertTrue(h.is_dirty)
        h.redo()
        self.assertTrue(h.is_dirty)
        h.mark_saved()
        self.assertFalse(h.is_dirty)

    def test_saved_at_start_undo_everything_is_clean(self):
        doc, h = setup()
        h.execute(Insert(0, "a"))
        h.undo()
        self.assertFalse(h.is_dirty)

    def test_saved_point_dropped_by_limit_after_step(self):
        doc, h = setup(limit=2)
        h.execute(Insert(0, "a"))
        h.mark_saved()
        h.execute(Insert(1, "b"))
        h.break_coalescing()
        h.execute(Insert(2, "c"))
        self.assertEqual(h.undo_depth, 2)
        self.assertTrue(h.is_dirty)
        h.undo()
        h.undo()
        self.assertEqual(doc.text, "a")
        self.assertFalse(h.is_dirty)

    def test_saved_at_start_lost_by_limit(self):
        doc, h = setup(limit=1)
        h.execute(Insert(0, "a"))
        h.break_coalescing()
        h.execute(Insert(1, "b"))
        h.undo()
        self.assertTrue(h.is_dirty)
        h.mark_saved()
        self.assertFalse(h.is_dirty)

    def test_saved_step_itself_dropped_and_later_exact(self):
        doc, h = setup(limit=1)
        h.execute(Insert(0, "a"))
        h.mark_saved()
        h.execute(Insert(1, "b"))
        h.undo()
        self.assertFalse(h.is_dirty)
        h.redo()
        self.assertTrue(h.is_dirty)

    def test_transaction_rollback_does_not_dirty(self):
        doc, h = setup()
        try:
            with h.transaction():
                h.execute(Insert(0, "a"))
                raise RuntimeError
        except RuntimeError:
            pass
        self.assertFalse(h.is_dirty)

    def test_dirty_with_transaction_undo(self):
        doc, h = setup()
        with h.transaction():
            h.execute(Insert(0, "a"))
            h.execute(Insert(1, "b"))
        h.mark_saved()
        h.undo()
        self.assertTrue(h.is_dirty)
        h.redo()
        self.assertFalse(h.is_dirty)

    def test_merging_after_dirty_revisit_is_not_saved(self):
        doc, h = setup()
        h.execute(Insert(0, "a"))
        h.mark_saved()
        h.undo()
        h.redo()
        h.execute(Insert(1, "b"))
        self.assertTrue(h.is_dirty)
        h.undo()
        self.assertFalse(h.is_dirty)


if __name__ == "__main__":
    unittest.main()
