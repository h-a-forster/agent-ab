import unittest

from crdtext import Document, Session


class Basics(unittest.TestCase):
    def test_document(self):
        d = Document("hello")
        d.insert(5, " world")
        d.insert(0, ">> ")
        d.delete(0, 3)
        self.assertEqual((d.text(), len(d)), ("hello world", 11))
        d.delete(5)
        self.assertEqual(d.text(), "helloworld")
        for bad in (lambda: d.insert(11, "x"), lambda: d.insert(-1, "x"), lambda: d.delete(9, 2), lambda: d.delete(0, -1)):
            with self.assertRaises(IndexError):
                bad()

    def test_session(self):
        s = Session("ab")
        self.assertEqual(s.edit("alice", "ins", 1, "X"), "aXb")
        self.assertEqual(s.edit("bob", "del", 0, 2), "b")
        self.assertEqual(len(s.log), 2)
        with self.assertRaises(ValueError):
            s.edit("bob", "move", 0, 1)
