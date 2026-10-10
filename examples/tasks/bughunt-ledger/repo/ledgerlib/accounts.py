"""Chart of accounts: a tree of typed accounts."""

from .errors import AccountError

TYPES = ("asset", "liability", "equity", "income", "expense")
DEBIT_NORMAL = {"asset", "expense"}


class Account:
    __slots__ = ("code", "name", "type", "parent", "currency")

    def __init__(self, code, name, type, parent=None, currency="USD"):
        self.code = code
        self.name = name
        self.type = type
        self.parent = parent
        self.currency = currency

    @property
    def debit_normal(self):
        return self.type in DEBIT_NORMAL

    def __repr__(self):
        return "Account(%r, %r)" % (self.code, self.name)


class Chart:
    """A tree of accounts keyed by code.  Children keep insertion order."""

    def __init__(self):
        self._accounts = {}
        self._children = {}

    def add(self, code, name, type, parent=None, currency=None):
        if code in self._accounts:
            raise AccountError("duplicate account %s" % code)
        if type not in TYPES:
            raise AccountError("unknown account type %r" % (type,))
        if parent is not None:
            par = self.get(parent)
            if par.type != type:
                raise AccountError("%s cannot be a %s under a %s" % (code, type, par.type))
            if currency is None:
                currency = par.currency
            elif currency != par.currency:
                raise AccountError("%s currency differs from its parent" % code)
        if currency is None:
            currency = "USD"
        account = Account(code, name, type, parent, currency)
        self._accounts[code] = account
        self._children[code] = []
        if parent is not None:
            self._children[parent].append(code)
        return account

    def get(self, code):
        try:
            return self._accounts[code]
        except KeyError:
            raise AccountError("unknown account %s" % code) from None

    def __contains__(self, code):
        return code in self._accounts

    def __len__(self):
        return len(self._accounts)

    def codes(self):
        return sorted(self._accounts)

    def children(self, code):
        self.get(code)
        return list(self._children[code])

    def descendants(self, code):
        """All accounts below ``code`` (not including ``code`` itself), depth first."""
        self.get(code)
        found = []
        stack = [code]
        while stack:
            current = stack.pop()
            found.append(current)
            stack.extend(reversed(self._children[current]))
        return found

    def ancestors(self, code):
        """Parents from the closest one up to the root."""
        chain = []
        current = self.get(code).parent
        while current is not None:
            chain.append(current)
            current = self._accounts[current].parent
        return chain

    def depth(self, code):
        return len(self.ancestors(code))

    def path(self, code):
        names = [self._accounts[c].name for c in reversed(self.ancestors(code))]
        names.append(self.get(code).name)
        return ":".join(names)

    def roots(self):
        return [c for c in self.codes() if self._accounts[c].parent is None]

    def is_leaf(self, code):
        return not self.children(code)

    def of_type(self, type):
        return [c for c in self.codes() if self._accounts[c].type == type]

    def walk(self):
        """Yield (code, depth) for the whole tree, roots sorted by code."""
        for root in self.roots():
            yield root, 0
            for code in self.descendants(root):
                yield code, self.depth(code)
