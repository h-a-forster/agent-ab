"""A central-server editing session: every client edit is applied to one shared Document in
arrival order, which is wrong for concurrent edits made against stale indexes."""
from .document import Document


class Session:
    def __init__(self, text=""):
        self.doc = Document(text)
        self.log = []

    def edit(self, client, kind, index, payload):
        """kind "ins": payload is the string to insert at `index`; "del": payload is a count."""
        if kind == "ins":
            self.doc.insert(index, payload)
        elif kind == "del":
            self.doc.delete(index, payload)
        else:
            raise ValueError("unknown edit kind %r" % (kind,))
        self.log.append((client, kind, index, payload))
        return self.doc.text()
