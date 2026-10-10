"""editdoc: undo/redo core for a text editor."""

from .commands import Delete, Insert
from .document import Document
from .history import History

__all__ = ["Delete", "Document", "History", "Insert"]
