# editdoc

The undo/redo core of a text editor: a `Document` buffer, reversible commands and a `History`.

```python
from editdoc import Delete, Document, History, Insert

doc = Document("hello")
hist = History(doc)
hist.execute(Insert(5, " world"))
hist.execute(Delete(0, 1))
doc.text          # 'ello world'
hist.undo()       # True
doc.text          # 'hello world'
hist.redo()
hist.is_dirty     # True until mark_saved()
```

* `document.py` `Document`: `text`, `insert(pos, text)`, `delete(pos, length)` (returns removed text);
  bad positions raise `IndexError`
* `commands.py` `Insert`, `Delete`: reversible commands (`apply(doc)` / `revert(doc)`)
* `history.py`  `History`: `execute`, `undo`, `redo`, `can_undo`, `can_redo`, `mark_saved`, `is_dirty`

Run the tests with `python -m unittest discover -s tests -t .`.
