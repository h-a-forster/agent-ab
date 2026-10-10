"""The parser."""

from .result import Namespace
from .spec import Option, Positional


class UsageError(ValueError):
    """Bad command line. The message names the offending option or argument."""


class Parser:
    def __init__(self, options=(), positionals=()):
        self.options = tuple(options)
        self.positionals = tuple(positionals)
        self._long = {}
        self._short = {}
        for opt in self.options:
            if opt.name in self._long:
                raise ValueError(f"duplicate option {opt.name!r}")
            self._long[opt.name] = opt
            if opt.short is not None:
                if opt.short in self._short:
                    raise ValueError(f"duplicate short option {opt.short!r}")
                self._short[opt.short] = opt
        for i, pos in enumerate(self.positionals):
            if pos.many and i != len(self.positionals) - 1:
                raise ValueError("a 'many' positional must be last")

    def parse(self, argv):
        values = {}
        given = set()
        words = []
        args = list(argv)
        i = 0
        while i < len(args):
            token = args[i]
            i += 1
            if token.startswith("--") and len(token) > 2:
                opt = self._long.get(token[2:])
                if opt is None:
                    raise UsageError(f"unknown option {token}")
                i = self._take(opt, token, args, i, values, given)
            elif token.startswith("-") and len(token) == 2 and token[1] in self._short:
                opt = self._short[token[1]]
                i = self._take(opt, token, args, i, values, given)
            elif token.startswith("-") and len(token) > 1:
                raise UsageError(f"unknown option {token}")
            else:
                words.append(token)
        for opt in self.options:
            if opt.key not in values:
                if opt.required:
                    raise UsageError(f"missing required option {opt.flag}")
                values[opt.key] = False if opt.kind == "flag" else opt.default
        self._bind_positionals(words, values)
        return Namespace(values)

    def _take(self, opt, token, args, i, values, given):
        if opt.kind == "flag":
            values[opt.key] = True
            return i
        if i >= len(args):
            raise UsageError(f"option {token} requires a value")
        values[opt.key] = self._convert(opt.type, args[i], opt.flag)
        return i + 1

    @staticmethod
    def _convert(fn, text, label):
        try:
            return fn(text)
        except (ValueError, TypeError) as exc:
            raise UsageError(f"invalid value {text!r} for {label}: {exc}") from None

    def _bind_positionals(self, words, values):
        idx = 0
        for pos in self.positionals:
            if pos.many:
                rest = words[idx:]
                if pos.required and not rest:
                    raise UsageError(f"missing required argument {pos.name}")
                values[pos.key] = [self._convert(pos.type, w, pos.name) for w in rest]
                idx = len(words)
            elif idx < len(words):
                values[pos.key] = self._convert(pos.type, words[idx], pos.name)
                idx += 1
            elif pos.required:
                raise UsageError(f"missing required argument {pos.name}")
            else:
                values[pos.key] = None
        if idx < len(words):
            raise UsageError(f"unexpected argument {words[idx]!r}")
