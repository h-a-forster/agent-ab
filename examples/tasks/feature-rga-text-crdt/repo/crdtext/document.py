"""A plain single-user text document (a list of characters)."""


class Document:
    def __init__(self, text=""):
        self._chars = list(text)

    def __len__(self):
        return len(self._chars)

    def text(self):
        return "".join(self._chars)

    def insert(self, index, s):
        """Insert the string `s` before the character at `index` (index == len appends)."""
        if not 0 <= index <= len(self._chars):
            raise IndexError("index out of range")
        self._chars[index:index] = list(s)

    def delete(self, index, count=1):
        """Delete `count` characters starting at `index`."""
        if count < 0 or not 0 <= index <= len(self._chars) - count:
            raise IndexError("range out of bounds")
        del self._chars[index:index + count]
