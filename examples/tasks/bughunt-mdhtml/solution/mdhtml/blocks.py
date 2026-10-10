"""Block-level parser: lines -> a list of block nodes."""

import re

from . import lists, tables

_FENCE_OPEN = re.compile(r"^( {0,3})(`{3,}|~{3,})\s*([^`\s]*)[^`]*$")
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_RULE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_QUOTE = re.compile(r"^ {0,3}> ?(.*)$")


class Node:
    kind = "node"

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__, ", ".join("%s=%r" % kv for kv in sorted(vars(self).items())))


class Heading(Node):
    def __init__(self, level, text):
        self.level = level
        self.text = text


class Paragraph(Node):
    def __init__(self, text):
        self.text = text


class CodeBlock(Node):
    def __init__(self, info, code):
        self.info = info
        self.code = code


class Quote(Node):
    def __init__(self, blocks):
        self.blocks = blocks


class ListBlock(Node):
    def __init__(self, ordered, start, items, loose):
        self.ordered = ordered
        self.start = start
        self.items = items  # list of lists of blocks
        self.loose = loose


class Table(Node):
    def __init__(self, header, aligns, rows):
        self.header = header
        self.aligns = aligns
        self.rows = rows


class Rule(Node):
    pass


def parse(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    return parse_blocks(text.split("\n"))


def is_block_start(line):
    """Would this line interrupt a paragraph?"""
    return bool(_FENCE_OPEN.match(line) or _ATX.match(line) or _RULE.match(line) or _QUOTE.match(line)
                or _interrupting_item(line))


def _interrupting_item(line):
    item = lists.match_item(line)
    if item is None or not item.text.strip():
        return False
    return not item.ordered or item.number == 1


def parse_blocks(lines):
    blocks = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = _FENCE_OPEN.match(line)
        if m:
            block, i = _parse_fence(lines, i, m)
            blocks.append(block)
            continue
        m = _ATX.match(line)
        if m:
            blocks.append(Heading(len(m.group(1)), (m.group(2) or "").strip()))
            i += 1
            continue
        if _RULE.match(line):
            blocks.append(Rule())
            i += 1
            continue
        if _QUOTE.match(line):
            block, i = _parse_quote(lines, i)
            blocks.append(block)
            continue
        if lists.match_item(line) and not _RULE.match(line):
            block, i = _parse_list(lines, i)
            blocks.append(block)
            continue
        if "|" in line and i + 1 < n and tables.is_delimiter_row(lines[i + 1]) \
                and len(tables.split_row(line)) == len(tables.split_row(lines[i + 1])):
            block, i = _parse_table(lines, i)
            blocks.append(block)
            continue
        block, i = _parse_paragraph(lines, i)
        blocks.append(block)
    return blocks


def _parse_fence(lines, i, m):
    indent = len(m.group(1))
    fence = m.group(2)
    info = m.group(3)
    body = []
    i += 1
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped and set(stripped) == {fence[0]} and len(stripped) >= len(fence):
            i += 1
            break
        line = lines[i]
        lead = len(line) - len(line.lstrip(" "))
        body.append(line[min(lead, indent):])
        i += 1
    code = "\n".join(body)
    return CodeBlock(info, code + "\n" if body else ""), i


def _parse_quote(lines, i):
    inner = []
    n = len(lines)
    while i < n:
        m = _QUOTE.match(lines[i])
        if m:
            inner.append(m.group(1))
            i += 1
        elif lines[i].strip() and inner and inner[-1].strip() and not is_block_start(lines[i]):
            inner.append(lines[i])  # lazy continuation of a paragraph
            i += 1
        else:
            break
    return Quote(parse_blocks(inner)), i


def _parse_list(lines, i):
    items, loose, end = lists.split_items(lines, i, is_block_start)
    first = items[0][0]
    parsed = [parse_blocks(body) for _, body in items]
    start = first.number if first.ordered else None
    return ListBlock(first.ordered, start, parsed, loose), end


def _parse_table(lines, i):
    header = tables.split_row(lines[i])
    aligns = tables.alignments(lines[i + 1])
    width = len(header)
    rows = []
    i += 2
    while i < len(lines) and lines[i].strip() and "|" in lines[i]:
        rows.append(tables.normalise(tables.split_row(lines[i]), width))
        i += 1
    return Table(header, aligns, rows), i


def _parse_paragraph(lines, i):
    collected = [lines[i].strip()]
    i += 1
    n = len(lines)
    while i < n and lines[i].strip():
        line = lines[i]
        s = _SETEXT.match(line)
        if s:
            level = 1 if s.group(1)[0] == "=" else 2
            return Heading(level, " ".join(collected)), i + 1
        if is_block_start(line):
            break
        collected.append(line.rstrip("\n").lstrip())
        i += 1
    text = "\n".join(collected)
    return Paragraph(text.rstrip()), i
