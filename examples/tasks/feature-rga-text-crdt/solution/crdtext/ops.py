"""Operations exchanged between replicas."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Op:
    """kind "ins": `id` is the new element's id (counter, replica), `ref` the id of the element it
    goes after (None = start of text), `char` the character. kind "del": `ref` is the id of the
    element to delete, `id` and `char` are None."""
    kind: str
    id: object = None
    ref: object = None
    char: object = None

    def to_dict(self):
        d = {"kind": self.kind, "ref": list(self.ref) if self.ref is not None else None}
        if self.kind == "ins":
            d["id"] = list(self.id)
            d["char"] = self.char
        return d

    @classmethod
    def from_dict(cls, d):
        ident = tuple(d["id"]) if d.get("id") is not None else None
        ref = tuple(d["ref"]) if d.get("ref") is not None else None
        return cls(d["kind"], ident, ref, d.get("char"))
