"""A small template language.

    {{ page.title | upper }}            output a value (HTML-escaped unless marked safe)
    {% for item in items %}..{% else %}..{% endfor %}
    {% if page.draft %}..{% elif x == "a" %}..{% else %}..{% endif %}

Filters: upper lower title length first last join(sep) default(x) truncate(n) date(fmt) safe escape.
``default`` replaces a value that is missing or ``None`` (not ``0``, ``""`` or ``False``).
"""

import re

from .errors import TemplateError
from .util import escape_html

_TOKEN = re.compile(r"(\{\{.*?\}\}|\{%.*?%\})", re.DOTALL)


class Safe(str):
    """Text that is already HTML and must not be escaped again."""


class Context:
    """A stack of scopes; lookups go from the innermost scope outwards."""

    def __init__(self, data=None):
        self.stack = [dict(data or {})]

    def push(self, scope=None):
        self.stack.append(dict(scope or {}))

    def pop(self):
        self.stack.pop()

    def set(self, name, value):
        self.stack[-1][name] = value

    def get(self, name):
        for scope in reversed(self.stack):
            if name in scope:
                return scope[name]
        return None


# -- expressions ------------------------------------------------------------

def _split_outside_quotes(text, sep):
    parts, current, quote = [], [], None
    depth = 0
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def _literal(token):
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return True, token[1:-1]
    if re.fullmatch(r"-?\d+", token):
        return True, int(token)
    if token in ("true", "false"):
        return True, token == "true"
    if token == "none":
        return True, None
    return False, None


def _lookup(path, ctx):
    parts = path.split(".")
    value = ctx.get(parts[0])
    for part in parts[1:]:
        if value is None:
            return None
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = getattr(value, part, None)
    return value


def evaluate_value(token, ctx):
    is_lit, value = _literal(token)
    if is_lit:
        return value
    token = token.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", token):
        raise TemplateError("bad expression %r" % token)
    return _lookup(token, ctx)


def _apply_filter(name, args, value):
    if name == "upper":
        return str(value).upper()
    if name == "lower":
        return str(value).lower()
    if name == "title":
        return str(value).title()
    if name == "length":
        return len(value) if value is not None else 0
    if name == "first":
        return value[0] if value else None
    if name == "last":
        return value[-1] if value else None
    if name == "join":
        return (args[0] if args else "").join(str(v) for v in (value or []))
    if name == "default":
        return args[0] if value is None else value
    if name == "truncate":
        limit = args[0]
        text = str(value)
        return text if len(text) <= limit else text[:max(limit - 3, 0)].rstrip() + "..."
    if name == "date":
        return value.strftime(args[0]) if value is not None else ""
    if name == "safe":
        return Safe(str(value))
    if name == "escape":
        return Safe(escape_html(value))
    raise TemplateError("unknown filter %r" % name)


def evaluate(expression, ctx):
    """Evaluate ``value | filter | filter(arg)``; returns the final Python value."""
    parts = _split_outside_quotes(expression, "|")
    value = evaluate_value(parts[0], ctx)
    for raw in parts[1:]:
        raw = raw.strip()
        m = re.fullmatch(r"([A-Za-z_]+)(?:\((.*)\))?", raw, re.DOTALL)
        if not m:
            raise TemplateError("bad filter %r" % raw)
        args = []
        if m.group(2) is not None and m.group(2).strip():
            for piece in _split_outside_quotes(m.group(2), ","):
                is_lit, lit = _literal(piece)
                if not is_lit:
                    raise TemplateError("filter arguments must be literals: %r" % piece)
                args.append(lit)
        value = _apply_filter(m.group(1), args, value)
    return value


def evaluate_condition(text, ctx):
    tokens = _split_condition(text)
    pos = [0]

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def take():
        pos[0] += 1
        return tokens[pos[0] - 1]

    def or_expr():
        left = and_expr()
        while peek() == "or":
            take()
            right = and_expr()
            left = bool(left) or bool(right)
        return left

    def and_expr():
        left = not_expr()
        while peek() == "and":
            take()
            right = not_expr()
            left = bool(left) and bool(right)
        return left

    def not_expr():
        if peek() == "not":
            take()
            return not not_expr()
        return comparison()

    def comparison():
        left = evaluate(take(), ctx)
        if peek() in ("==", "!="):
            op = take()
            right = evaluate(take(), ctx)
            return (left == right) if op == "==" else (left != right)
        return left

    if not tokens:
        raise TemplateError("empty condition")
    result = or_expr()
    if pos[0] != len(tokens):
        raise TemplateError("bad condition %r" % text)
    return bool(result)


def _split_condition(text):
    tokens, current, quote = [], [], None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            current.append(ch)
        elif ch.isspace():
            if current:
                tokens.append("".join(current))
                current = []
        elif text[i:i + 2] in ("==", "!="):
            if current:
                tokens.append("".join(current))
                current = []
            tokens.append(text[i:i + 2])
            i += 1
        else:
            current.append(ch)
        i += 1
    if current:
        tokens.append("".join(current))
    return tokens


# -- parsing and rendering --------------------------------------------------

class Text:
    def __init__(self, text):
        self.text = text


class Output:
    def __init__(self, expression):
        self.expression = expression


class For:
    def __init__(self, var, expression):
        self.var = var
        self.expression = expression
        self.body = []
        self.else_body = []


class If:
    def __init__(self, condition):
        self.branches = [(condition, [])]
        self.else_body = []


class Template:
    def __init__(self, source):
        self.source = source
        self.nodes = self._parse(source)

    @staticmethod
    def _parse(source):
        root = []
        stack = [("root", root, None)]
        for token in _TOKEN.split(source):
            if not token:
                continue
            if token.startswith("{{"):
                stack[-1][1].append(Output(token[2:-2].strip()))
            elif token.startswith("{%"):
                words = token[2:-2].strip().split(None, 1)
                keyword = words[0] if words else ""
                rest = words[1] if len(words) > 1 else ""
                Template._tag(keyword, rest, stack)
            else:
                stack[-1][1].append(Text(token))
        if len(stack) != 1:
            raise TemplateError("unclosed {%% %s %%} block" % stack[-1][0])
        return root

    @staticmethod
    def _tag(keyword, rest, stack):
        kind, target, _ = stack[-1]
        if keyword == "for":
            m = re.fullmatch(r"([A-Za-z_]\w*)\s+in\s+(.+)", rest)
            if not m:
                raise TemplateError("bad for tag: %r" % rest)
            node = For(m.group(1), m.group(2))
            target.append(node)
            stack.append(("for", node.body, node))
        elif keyword == "if":
            node = If(rest)
            target.append(node)
            stack.append(("if", node.branches[0][1], node))
        elif keyword == "elif":
            if kind != "if":
                raise TemplateError("elif outside if")
            node = stack[-1][2]
            body = []
            node.branches.append((rest, body))
            stack[-1] = ("if", body, node)
        elif keyword == "else":
            if kind not in ("if", "for"):
                raise TemplateError("else outside if/for")
            node = stack[-1][2]
            node.else_body = []
            stack[-1] = (kind, node.else_body, node)
        elif keyword in ("endif", "endfor"):
            expected = "if" if keyword == "endif" else "for"
            if kind != expected:
                raise TemplateError("unexpected %s" % keyword)
            stack.pop()
        else:
            raise TemplateError("unknown tag %r" % keyword)

    def render(self, data):
        ctx = data if isinstance(data, Context) else Context(data)
        return "".join(self._render_nodes(self.nodes, ctx))

    def _render_nodes(self, nodes, ctx):
        out = []
        for node in nodes:
            if isinstance(node, Text):
                out.append(node.text)
            elif isinstance(node, Output):
                value = evaluate(node.expression, ctx)
                if value is None:
                    continue
                out.append(value if isinstance(value, Safe) else escape_html(value))
            elif isinstance(node, If):
                out.extend(self._render_if(node, ctx))
            else:
                out.extend(self._render_for(node, ctx))
        return out

    def _render_if(self, node, ctx):
        for condition, body in node.branches:
            if evaluate_condition(condition, ctx):
                return self._render_nodes(body, ctx)
        return self._render_nodes(node.else_body, ctx)

    def _render_for(self, node, ctx):
        items = evaluate(node.expression, ctx) or []
        items = list(items)
        if not items:
            return self._render_nodes(node.else_body, ctx)
        out = []
        ctx.push()
        try:
            for index, item in enumerate(items):
                ctx.set(node.var, item)
                ctx.set("loop", {"index": index + 1, "index0": index, "first": index == 0,
                                 "last": index == len(items) - 1, "length": len(items)})
                out.extend(self._render_nodes(node.body, ctx))
        finally:
            ctx.pop()
        return out


def render_string(source, data):
    return Template(source).render(data)
