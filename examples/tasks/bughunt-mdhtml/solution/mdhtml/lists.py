"""List item recognition and grouping."""

import re

ITEM = re.compile(r"^( {0,3})([-*+]|\d{1,9}[.)])( +|$)(.*)$")


class ItemMatch:
    """A recognised list marker line."""

    def __init__(self, m):
        self.indent = len(m.group(1))
        self.marker = m.group(2)
        spaces = len(m.group(3))
        rest = m.group(4)
        if spaces == 0 or spaces > 4 or not rest.strip():
            spaces = 1
        self.content_indent = self.indent + len(self.marker) + spaces
        self.text = rest if m.group(3) else ""
        if len(m.group(3)) > 4:
            self.text = " " * (len(m.group(3)) - 1) + rest
        self.ordered = self.marker[0].isdigit()
        self.delimiter = self.marker[-1] if self.ordered else self.marker
        self.number = int(self.marker[:-1]) if self.ordered else None

    def same_list(self, other):
        return self.ordered == other.ordered and self.delimiter == other.delimiter


def match_item(line):
    m = ITEM.match(line)
    return ItemMatch(m) if m else None


def split_items(lines, start, is_block_start):
    """Group consecutive lines from ``start`` into list items.

    Returns ``(items, loose, next_index)`` where ``items`` is a list of
    ``(ItemMatch, item_lines)``.  A list is *loose* when a blank line separates any two of
    its items.  Continuation lines must be indented to the item's content column; a
    non-blank line directly after item text (no blank line) continues the paragraph.
    """
    first = match_item(lines[start])
    items = []
    loose = False
    i = start
    n = len(lines)
    while i < n:
        head = match_item(lines[i])
        if head is None or not head.same_list(first):
            break
        body = [head.text]
        i += 1
        blanks = 0
        while i < n:
            line = lines[i]
            if not line.strip():
                blanks += 1
                i += 1
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent >= head.content_indent:
                body.extend([""] * blanks)
                body.append(line[head.content_indent:])
                blanks = 0
                i += 1
            elif blanks == 0 and match_item(line) is None and not is_block_start(line):
                body.append(line.strip())
                i += 1
            else:
                break
        items.append((head, body))
        nxt = match_item(lines[i]) if i < n else None
        if nxt is not None and nxt.same_list(first):
            if blanks:
                loose = True
            continue
        break
    return items, loose, i
