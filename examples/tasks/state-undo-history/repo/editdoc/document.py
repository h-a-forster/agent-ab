"""A text buffer."""


class Document:
    def __init__(self, text=""):
        self._text = text

    @property
    def text(self):
        return self._text

    def __len__(self):
        return len(self._text)

    def insert(self, pos, text):
        if not 0 <= pos <= len(self._text):
            raise IndexError(f"insert position {pos} out of range")
        self._text = self._text[:pos] + text + self._text[pos:]

    def delete(self, pos, length):
        if pos < 0 or length < 0 or pos + length > len(self._text):
            raise IndexError(f"delete range {pos}+{length} out of range")
        removed = self._text[pos:pos + length]
        self._text = self._text[:pos] + self._text[pos + length:]
        return removed
