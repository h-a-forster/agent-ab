"""The parser."""

import re

from .result import Namespace
from .spec import Option, Positional

_NUMBER = re.compile(r"^-\d+(\.\d+)?$")


class UsageError(ValueError):
    """Bad command line. The message names the offending option or argument."""


class Parser:
    def __init__(self, options=(), positionals=(), commands=None):
        self.options = tuple(options)
        self.positionals = tuple(positionals)
        self.commands = dict(commands) if commands else {}
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
        if self.commands and self.positionals:
            raise ValueError("a parser with commands cannot have positionals")

    def parse(self, argv):
        values = {}
        words = []
        args = list(argv)
        command = sub = None
        i = 0
        only_words = False
        while i < len(args):
            token = args[i]
            i += 1
            if only_words or token == "-" or not token.startswith("-") or _NUMBER.match(token):
                if self.commands:
                    command, sub = self._dispatch(token, args[i:])
                    i = len(args)
                    break
                words.append(token)
            elif token == "--":
                only_words = True
            elif token.startswith("--"):
                name, eq, text = token[2:].partition("=")
                opt = self._long.get(name)
                if opt is None:
                    raise UsageError(f"unknown option --{name}")
                if eq:
                    if not opt.takes_value:
                        raise UsageError(f"option --{name} does not take a value")
                    self._store(opt, text, values)
                elif opt.takes_value:
                    if i >= len(args):
                        raise UsageError(f"option --{name} requires a value")
                    self._store(opt, args[i], values)
                    i += 1
                else:
                    self._store(opt, None, values)
            else:
                i = self._cluster(token, args, i, values)
        if self.commands and command is None:
            raise UsageError("missing command (one of: " + ", ".join(sorted(self.commands)) + ")")
        for opt in self.options:
            if opt.key not in values:
                if opt.required:
                    raise UsageError(f"missing required option {opt.flag}")
                values[opt.key] = opt.initial()
        self._bind_positionals(words, values)
        return Namespace(values, command, sub)

    def _dispatch(self, name, rest):
        parser = self.commands.get(name)
        if parser is None:
            raise UsageError(f"unknown command {name!r} (choose from: " + ", ".join(sorted(self.commands)) + ")")
        return name, parser.parse(rest)

    def _cluster(self, token, args, i, values):
        letters = token[1:]
        for pos, ch in enumerate(letters):
            opt = self._short.get(ch)
            if opt is None:
                raise UsageError(f"unknown option -{ch}")
            if not opt.takes_value:
                self._store(opt, None, values)
                continue
            rest = letters[pos + 1:]
            if rest:
                self._store(opt, rest, values)
            elif i < len(args):
                self._store(opt, args[i], values)
                i += 1
            else:
                raise UsageError(f"option -{ch} requires a value")
            break
        return i

    def _store(self, opt, text, values):
        if opt.kind == "flag":
            values[opt.key] = True
        elif opt.kind == "count":
            values[opt.key] = values.get(opt.key, 0) + 1
        elif opt.kind == "append":
            if opt.key not in values:
                values[opt.key] = []
            values[opt.key].append(self._convert(opt.type, text, opt.flag))
        else:
            values[opt.key] = self._convert(opt.type, text, opt.flag)

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
