"""The Sheet: raw cell contents, dependency tracking and cached evaluation."""

from . import parser as P
from .errors import CYCLE, SYNTAX, FormulaSyntaxError, SheetError
from .evaluator import Evaluator
from .refs import cell_sort_key, expand_range, normalize_key, parse_ref


def _number(text):
    """int / float for numeric text, else None (``nan``, ``inf`` and friends are plain text)."""
    s = text.strip()
    if not s or not (s[-1].isdigit() or s[-1] == "."):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return None


def parse_raw(text):
    """Classify raw cell text -> ``("formula", tree)`` or ``("value", python value)``."""
    if text.startswith("=") and len(text) > 1:
        return ("formula", P.parse_formula(text[1:]))
    stripped = text.strip()
    if stripped.upper() in ("TRUE", "FALSE"):
        return ("value", stripped.upper() == "TRUE")
    number = _number(text)
    return ("value", text if number is None else number)


class Sheet:
    def __init__(self):
        self._raw = {}
        self._parsed = {}
        self._deps = {}
        self._rdeps = {}
        self._cache = {}
        self._evaluating = set()
        self._evaluator = Evaluator(self._ref_value)

    # -- editing -----------------------------------------------------------
    def set(self, cell, raw):
        key = normalize_key(cell)
        raw = "" if raw is None else str(raw)
        self._drop_edges(key)
        if raw == "":
            self._raw.pop(key, None)
            self._parsed.pop(key, None)
        else:
            self._raw[key] = raw
            try:
                kind, payload = parse_raw(raw)
            except FormulaSyntaxError:
                kind, payload = "syntax", None
            self._parsed[key] = (kind, payload)
            if kind == "formula":
                self._add_edges(key, payload)
        self._invalidate(key)

    def set_many(self, mapping):
        for cell, raw in mapping.items():
            self.set(cell, raw)

    def clear(self, cell):
        self.set(cell, "")

    def _add_edges(self, key, tree):
        deps = set()
        for node in P.walk(tree):
            if isinstance(node, P.CellRef):
                deps.add(node.ref.key)
            elif isinstance(node, P.RangeRef):
                try:
                    deps.update(expand_range(node.start, node.end))
                except SheetError:
                    pass
        self._deps[key] = deps
        for dep in deps:
            self._rdeps.setdefault(dep, set()).add(key)

    def _drop_edges(self, key):
        for dep in self._deps.pop(key, ()):
            users = self._rdeps.get(dep)
            if users:
                users.discard(key)
                if not users:
                    del self._rdeps[dep]

    def _invalidate(self, key):
        """Forget cached values of ``key`` and of everything that depends on it, directly or not."""
        stack = [key]
        seen = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            self._cache.pop(current, None)
            stack.extend(self._rdeps.get(current, ()))

    # -- reading -----------------------------------------------------------
    def raw(self, cell):
        return self._raw.get(normalize_key(cell), "")

    def get(self, cell):
        return self._value(normalize_key(cell))

    def _ref_value(self, key):
        if key in self._evaluating:
            return CYCLE
        return self._value(key)

    def _value(self, key):
        if key in self._cache:
            return self._cache[key]
        entry = self._parsed.get(key)
        if entry is None:
            return None
        kind, payload = entry
        if kind == "value":
            value = payload
        elif kind == "syntax":
            value = SYNTAX
        else:
            self._evaluating.add(key)
            try:
                value = self._evaluator.evaluate(payload)
            finally:
                self._evaluating.discard(key)
        self._cache[key] = value
        return value

    def cells(self):
        """Keys of non-empty cells in row-major order."""
        return sorted(self._raw, key=cell_sort_key)

    def values(self):
        return {key: self.get(key) for key in self.cells()}

    def dependencies(self, cell):
        return sorted(self._deps.get(normalize_key(cell), ()), key=cell_sort_key)

    def dependents(self, cell):
        """Cells whose formulas directly reference ``cell``."""
        return sorted(self._rdeps.get(normalize_key(cell), ()), key=cell_sort_key)

    # -- copying -----------------------------------------------------------
    def copy(self, src, dst):
        """Copy a cell; formulas get their relative references shifted like a fill / paste."""
        s, d = parse_ref(src), parse_ref(dst)
        raw = self.raw(src)
        entry = self._parsed.get(s.key)
        if entry is None or entry[0] != "formula":
            self.set(dst, raw)
            return
        try:
            shifted = P.shift_formula(entry[1], d.row - s.row, d.col - s.col)
        except P.ShiftError:
            self.set(dst, "=#REF!")
            return
        self.set(dst, "=" + P.unparse(shifted))

    def fill_down(self, src, count):
        s = parse_ref(src)
        targets = []
        for i in range(1, count + 1):
            target = "%s%d" % (s.key.rstrip("0123456789"), s.row + i)
            self.copy(src, target)
            targets.append(target)
        return targets
