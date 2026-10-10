"""RGA replicated text: elements form a tree (each insert hangs below the element it goes
after); the text is the depth-first walk where siblings are ordered by descending id.
Stored as a flat sequence in blocks so index lookups and inserts stay fast."""
from .ops import Op

BLOCK = 128


class _Node:
    __slots__ = ("id", "char", "alive", "block")

    def __init__(self, ident, char, block):
        self.id = ident
        self.char = char
        self.alive = True
        self.block = block


class _Block:
    __slots__ = ("nodes", "visible")

    def __init__(self, nodes):
        self.nodes = nodes
        self.visible = len(nodes)


class Replica:
    def __init__(self, replica_id):
        if not isinstance(replica_id, str) or not replica_id:
            raise ValueError("replica id must be a non-empty string")
        self.replica_id = replica_id
        self.clock = 0
        self._blocks = [_Block([])]
        self._nodes = {}
        self._pending = {}       # missing dependency id -> list of ops
        self._pending_keys = set()
        self._history = []
        self._total = 0

    # ---- queries
    def text(self):
        return "".join(n.char for b in self._blocks for n in b.nodes if n.alive)

    def __len__(self):
        return sum(b.visible for b in self._blocks)

    def visible_ids(self):
        return [n.id for b in self._blocks for n in b.nodes if n.alive]

    def pending(self):
        return len(self._pending_keys)

    def history(self):
        return list(self._history)

    # ---- positions
    def _visible_node(self, index):
        for b in self._blocks:
            if index < b.visible:
                for n in b.nodes:
                    if n.alive:
                        if index == 0:
                            return n
                        index -= 1
            index -= b.visible
        raise AssertionError("unreachable")

    def _insert_after(self, ref_node, node):
        """Place `node` right after `ref_node` (None = start), skipping newer siblings' subtrees."""
        bi, ii = (0, 0) if ref_node is None else self._where(ref_node, after=True)
        blocks = self._blocks
        while True:
            b = blocks[bi]
            if ii < len(b.nodes):
                if b.nodes[ii].id > node.id:
                    ii += 1
                    continue
                break
            if bi + 1 < len(blocks):
                bi, ii = bi + 1, 0
                continue
            break
        b = blocks[bi]
        b.nodes.insert(ii, node)
        node.block = b
        b.visible += 1
        if len(b.nodes) > 2 * BLOCK:
            half = len(b.nodes) // 2
            new = _Block(b.nodes[half:])
            new.visible = sum(1 for n in new.nodes if n.alive)
            b.nodes = b.nodes[:half]
            b.visible = sum(1 for n in b.nodes if n.alive)
            for n in new.nodes:
                n.block = new
            blocks.insert(blocks.index(b) + 1, new)

    def _where(self, node, after):
        b = node.block
        bi = self._blocks.index(b)
        ii = b.nodes.index(node) + (1 if after else 0)
        return bi, ii

    # ---- applying operations
    def _ready(self, op):
        if op.kind == "ins":
            return op.ref is None or op.ref in self._nodes
        return op.ref in self._nodes

    def _key(self, op):
        return ("i", op.id) if op.kind == "ins" else ("d", op.ref)

    def _known(self, op):
        if op.kind == "ins":
            return op.id in self._nodes
        node = self._nodes.get(op.ref)
        return node is not None and not node.alive

    def _do(self, op):
        if op.kind == "ins":
            node = _Node(op.id, op.char, None)
            self._nodes[op.id] = node
            self._insert_after(self._nodes[op.ref] if op.ref is not None else None, node)
            if op.id[0] > self.clock:
                self.clock = op.id[0]
        else:
            node = self._nodes[op.ref]
            node.alive = False
            node.block.visible -= 1
        self._history.append(op)

    def apply(self, op):
        """Apply a remote (or repeated) operation; returns how many operations were newly applied."""
        if op.kind not in ("ins", "del"):
            raise ValueError("unknown op kind %r" % (op.kind,))
        if self._known(op) or self._key(op) in self._pending_keys:
            return 0
        if not self._ready(op):
            self._pending.setdefault(op.ref, []).append(op)
            self._pending_keys.add(self._key(op))
            return 0
        applied = 0
        work = [op]
        while work:
            cur = work.pop()
            if self._known(cur):
                continue
            self._do(cur)
            applied += 1
            if cur.kind == "ins":
                for waiting in self._pending.pop(cur.id, []):
                    self._pending_keys.discard(self._key(waiting))
                    work.append(waiting)
        return applied

    # ---- local operations
    def insert(self, index, char):
        if not isinstance(char, str) or len(char) != 1:
            raise ValueError("char must be a single character")
        n = len(self)
        if not 0 <= index <= n:
            raise IndexError("index out of range")
        ref = self._visible_node(index - 1).id if index > 0 else None
        op = Op("ins", (self.clock + 1, self.replica_id), ref, char)
        self.apply(op)
        return op

    def insert_text(self, index, s):
        ops = []
        for k, ch in enumerate(s):
            ops.append(self.insert(index + k, ch))
        return ops

    def delete(self, index):
        if not 0 <= index < len(self):
            raise IndexError("index out of range")
        op = Op("del", None, self._visible_node(index).id, None)
        self.apply(op)
        return op
