"""Generic adapter: run any argv template and read usage from an optional ``usage.json``."""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_ab.adapters.base import Adapter
from agent_ab.errors import ConfigError
from agent_ab.model import AgentInvocation, AgentSpec, AgentUsage, ProcResult, TrialContext

PLACEHOLDERS: frozenset[str] = frozenset(
    {"prompt_file", "prompt", "workspace", "artifacts", "model", "effort", "python", "seed", "root"}
)

USAGE_FILE = "usage.json"
PROMPT_FILE = "prompt.md"

_TOKEN = re.compile(r"\{\{|\}\}|\{([^{}]*)\}|[{}]")

_INT_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "turns")
_STR_FIELDS = ("final_message", "infra_error")


def _expand(template: str, values: Mapping[str, str]) -> str:
    """Substitute ``{name}`` placeholders; ``{{``/``}}`` are literal braces.

    Raises ``ConfigError`` for unknown names or unbalanced braces.
    """

    def repl(m: re.Match[str]) -> str:
        tok = m.group(0)
        if tok == "{{":
            return "{"
        if tok == "}}":
            return "}"
        name = m.group(1)
        if name is None:
            raise ConfigError(f"unbalanced brace in {template!r} (use {{{{ or }}}} for literals)")
        if name not in values:
            raise ConfigError(f"unknown placeholder {{{name}}} in {template!r}")
        return values[name]

    return _TOKEN.sub(repl, template)


def _template_problems(template: tuple[str, ...]) -> list[str]:
    dummy = dict.fromkeys(PLACEHOLDERS, "")
    problems = []
    for item in template:
        try:
            _expand(item, dummy)
        except ConfigError as e:
            problems.append(f"command: {e}")
    return problems


def _resolve(name: str) -> str | None:
    """Full path of an executable, honouring PATHEXT on Windows (so ``.cmd`` shims resolve)."""
    return shutil.which(name)


def _is_number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def _check_bool(options: Mapping[str, Any], key: str) -> list[str]:
    if key in options and not isinstance(options[key], bool):
        return [f"option {key!r} must be true or false"]
    return []


def _read_usage_file(path: Path) -> AgentUsage:
    """Read the ``usage.json`` contract leniently: wrong types and unknown keys are ignored."""
    usage = AgentUsage()
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return usage
    if not isinstance(data, dict):
        return usage
    cost = data.get("cost_usd")
    if _is_number(cost) and cost >= 0:
        usage.cost_usd = float(cost)
    for key in _INT_FIELDS:
        v = data.get(key)
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            setattr(usage, key, v)
    for key in _STR_FIELDS:
        v = data.get(key)
        if isinstance(v, str) and v:
            setattr(usage, key, v)
    return usage


def _shell_argv(line: str, artifacts: Path) -> list[str]:
    # AgentInvocation has no shell flag, so the platform shell is invoked explicitly.
    if os.name == "nt":
        # Passing the line as one argv item would get its quotes backslash-escaped, which
        # cmd.exe does not understand; a batch file keeps the line verbatim.
        script = artifacts / "command.cmd"
        script.write_text(f"@chcp 65001 >nul\r\n@{line}\r\n", encoding="utf-8", newline="")
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(script)]
    return ["/bin/sh", "-c", line]


def _shell_quote(value: str) -> str:
    return subprocess.list2cmdline([value]) if os.name == "nt" else shlex.quote(value)


class CommandAdapter(Adapter):
    """Runs an arbitrary argv template; the agent may report usage via ``{artifacts}/usage.json``.

    A non-zero exit code is not an infrastructure error: it is recorded and the check still runs.
    """

    name = "command"
    option_keys = frozenset({"stdin", "shell"})

    def validate(self, spec: AgentSpec) -> list[str]:
        problems = super().validate(spec)
        if not spec.command:
            problems.append("adapter 'command' requires a non-empty 'command' argv template")
        elif not all(isinstance(x, str) for x in spec.command):
            problems.append("command: every item must be a string")
        else:
            problems += _template_problems(tuple(spec.command))
        problems += _check_bool(spec.options, "stdin")
        problems += _check_bool(spec.options, "shell")
        return problems

    def check_available(self, spec: AgentSpec) -> str | None:
        if not spec.command or spec.options.get("shell"):
            return None
        exe = spec.command[0]
        if "{" in exe or _resolve(exe) is not None:
            return None
        return f"command: executable {exe!r} not found on PATH"

    def build(self, ctx: TrialContext) -> AgentInvocation:
        spec = ctx.spec
        ctx.artifacts.mkdir(parents=True, exist_ok=True)
        prompt_path = ctx.artifacts / PROMPT_FILE
        prompt_path.write_text(ctx.prompt, encoding="utf-8", newline="\n")
        values = {
            "prompt_file": str(prompt_path),
            "prompt": ctx.prompt,
            "workspace": str(ctx.workspace),
            "artifacts": str(ctx.artifacts),
            "model": spec.model or "",
            "effort": spec.effort or "",
            "python": sys.executable,
            "seed": str(ctx.seed),
            "root": str(ctx.root) if ctx.root is not None else str(ctx.workspace),
        }
        template = tuple(spec.command or ())
        if spec.options.get("shell"):
            quoted = {k: _shell_quote(v) for k, v in values.items()}
            argv = _shell_argv(" ".join(_expand(item, quoted) for item in template), ctx.artifacts)
        else:
            argv = [_expand(item, values) for item in template]
            if argv:
                argv[0] = _resolve(argv[0]) or argv[0]
        return AgentInvocation(
            argv=argv,
            env=dict(spec.env),
            stdin=ctx.prompt if spec.options.get("stdin") else None,
            cwd=ctx.workspace,
        )

    def parse(self, ctx: TrialContext, result: ProcResult) -> AgentUsage:
        return _read_usage_file(ctx.artifacts / USAGE_FILE)
