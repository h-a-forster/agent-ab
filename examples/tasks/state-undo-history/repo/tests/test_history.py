import unittest

from editdoc import Delete, Document, History, Insert


class Basics(unittest.TestCase):
    def setUp(self):
        self.doc = Document("hello")
        self.hist = History(self.doc)

    def test_undo_redo(self):
        self.hist.execute(Insert(5, " world"))
        self.hist.execute(Delete(0, 1))
        self.assertEqual(self.doc.text, "ello world")
        self.assertTrue(self.hist.undo())
        self.assertEqual(self.doc.text, "hello world")
        self.assertTrue(self.hist.undo())
        self.assertFalse(self.hist.undo())
        self.assertEqual(self.doc.text, "hello")
        self.assertTrue(self.hist.redo())
        self.assertEqual(self.doc.text, "hello world")

    def test_new_command_clears_redo(self):
        self.hist.execute(Insert(0, "a"))
        self.hist.undo()
        self.assertTrue(self.hist.can_redo)
        self.hist.execute(Insert(0, "b"))
        self.assertFalse(self.hist.can_redo)

    def test_dirty(self):
        self.assertFalse(self.hist.is_dirty)
        self.hist.execute(Insert(0, "a"))
        self.assertTrue(self.hist.is_dirty)
        self.hist.mark_saved()
        self.assertFalse(self.hist.is_dirty)
        self.hist.undo()
        self.assertTrue(self.hist.is_dirty)
        self.hist.redo()
        self.assertFalse(self.hist.is_dirty)

    def test_failed_command_leaves_history_alone(self):
        with self.assertRaises(IndexError):
            self.hist.execute(Insert(99, "x"))
        self.assertFalse(self.hist.can_undo)
        self.assertEqual(self.doc.text, "hello")


if __name__ == "__main__":
    unittest.main()
