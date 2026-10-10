"""CommonMark emphasis: the delimiter-stack algorithm (spec 'process emphasis').

build_tree(nodes) -> list of ("text", s) / ("code", s) / ("em", children) / ("strong", children).
"""


class _N:
    __slots__ = ("kind", "value", "children", "prev", "next")

    def __init__(self, kind, value=None):
        self.kind = kind
        self.value = value
        self.children = None
        self.prev = None
        self.next = None


class _D:
    __slots__ = ("ch", "orig", "count", "can_open", "can_close", "node", "prev", "next")


def build_tree(nodes):
    head = _N("head")
    tail = head
    top = None     # last delimiter pushed
    first_delim = None
    for item in nodes:
        if item[0] == "delim":
            n = _N("text", item[1] * item[2])
            d = _D()
            d.ch, d.orig, d.count, d.can_open, d.can_close = item[1], item[2], item[2], item[3], item[4]
            d.node = n
            d.prev, d.next = top, None
            if top is not None:
                top.next = d
            else:
                first_delim = d
            top = d
        else:
            n = _N(item[0], item[1])
        n.prev = tail
        tail.next = n
        tail = n

    def remove_delim(d):
        nonlocal top, first_delim
        if d.prev is not None:
            d.prev.next = d.next
        else:
            first_delim = d.next
        if d.next is not None:
            d.next.prev = d.prev
        else:
            top = d.prev

    def unlink(n):
        n.prev.next = n.next
        if n.next is not None:
            n.next.prev = n.prev

    bottoms = {}
    closer = first_delim
    while closer is not None:
        if not closer.can_close:
            closer = closer.next
            continue
        key = (closer.ch, closer.can_open, closer.orig % 3)
        bottom = bottoms.get(key)
        opener = closer.prev
        found = None
        while opener is not None and opener is not bottom:
            if opener.ch == closer.ch and opener.can_open:
                odd = (closer.can_open or opener.can_close) and closer.orig % 3 != 0 and (opener.orig + closer.orig) % 3 == 0
                if not odd:
                    found = opener
                    break
            opener = opener.prev
        old = closer
        if found is None:
            closer = closer.next
            bottoms[key] = old.prev
            if not old.can_open:
                remove_delim(old)
            continue
        opener = found
        use = 2 if (closer.count >= 2 and opener.count >= 2) else 1
        opener.count -= use
        closer.count -= use
        opener.node.value = opener.node.value[:-use]
        closer.node.value = closer.node.value[:-use]
        box = _N("strong" if use == 2 else "em")
        box.children = []
        cur = opener.node.next
        while cur is not closer.node:
            nxt = cur.next
            box.children.append(cur)
            cur = nxt
        box.prev = opener.node
        box.next = closer.node
        opener.node.next = box
        closer.node.prev = box
        # drop the delimiters between opener and closer
        d = closer.prev
        while d is not opener:
            p = d.prev
            remove_delim(d)
            d = p
        if opener.count == 0:
            unlink(opener.node)
            remove_delim(opener)
        if closer.count == 0:
            unlink(closer.node)
            nxt = closer.next
            remove_delim(closer)
            closer = nxt
    # convert to tuples, iteratively
    root = []
    stack = [(root, iter(_walk(head.next)))]
    result = root
    while stack:
        out, it = stack[-1]
        node = next(it, None)
        if node is None:
            stack.pop()
            continue
        if node.kind in ("em", "strong"):
            kids = []
            out.append((node.kind, kids))
            stack.append((kids, iter(node.children)))
        elif node.value != "":
            out.append((node.kind, node.value))
    return result


def _walk(n):
    while n is not None:
        yield n
        n = n.next
