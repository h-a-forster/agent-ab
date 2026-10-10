"""Error values and exceptions."""


class CellError:
    """A spreadsheet error value such as ``#DIV/0!``.  Compared and hashed by its code."""

    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code

    def __eq__(self, other):
        return isinstance(other, CellError) and other.code == self.code

    def __hash__(self):
        return hash(self.code)

    def __repr__(self):
        return "CellError(%r)" % self.code

    def __str__(self):
        return self.code


DIV0 = CellError("#DIV/0!")
VALUE = CellError("#VALUE!")
REF = CellError("#REF!")
NAME = CellError("#NAME?")
NUM = CellError("#NUM!")
CYCLE = CellError("#CYCLE!")
SYNTAX = CellError("#ERROR!")


class ErrorSignal(Exception):
    """Raised inside the evaluator to abort a formula with an error value."""

    def __init__(self, error):
        super().__init__(error.code)
        self.error = error


class SheetError(Exception):
    """Misuse of the Sheet API (bad cell name, bad copy target, ...)."""


class FormulaSyntaxError(Exception):
    """A formula cannot be tokenized or parsed."""

    def __init__(self, message, pos=None):
        super().__init__(message if pos is None else "%s (at %d)" % (message, pos))
        self.pos = pos
