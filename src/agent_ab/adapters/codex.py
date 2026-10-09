"""Adapter for the Codex CLI in non-interactive mode (``codex exec --json``)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from agent_ab.adapters.base import Adapter, read_text
from agent_ab.adapters.claude_code import _int, _looks_like_infra, _tail
from agent_ab.adapters.command import _check_bool, _is_number, _resolve
from agent_ab.model import AgentInvocation, AgentSpec, AgentUsage, ProcResult, TrialContext

SANDBOXES: frozenset[str] = frozenset({"read-only", "workspace-write", "danger-full-access"})
EFFORTS: frozenset[str] = frozenset({"none", "minimal", "low", "medium", "high", "xhigh"})
_PRICES = ("price_input_per_mtok", "price_cached_input_per_mtok", "price_output_per_mtok")
_MESSAGE_ITEMS = frozenset({"agent_message", "assistant_message"})  # older releases used the latter

_STDOUT_LIMIT = 16 * 1024 * 1024


def _error_text(event: Mapping[str, Any]) -> str:
    err = event.get("error")
    if isinstance(err, Mapping):
        msg = err.get("message")
        if isinstance(msg, str):
            return msg
    if isinstance(err, str):
        return err
    msg = event.get("message")
    return msg if isinstance(msg, str) else json.dumps(event)[:500]


def _cost(
    options: Mapping[str, Any], input_tokens: int, cached: int, output_tokens: int
) -> float | None:
    p_in = options.get("price_input_per_mtok")
    p_cached = options.get("price_cached_input_per_mtok")
    p_out = options.get("price_output_per_mtok")
    if p_in is None or p_out is None or (cached and p_cached is None):
        return None
    # Codex reports input_tokens INCLUDING cached tokens, so cached ones are billed separately.
    uncached = max(input_tokens - cached, 0)
    total = uncached * p_in + output_tokens * p_out + (cached * p_cached if cached else 0)
    return total / 1_000_000


def parse_events(
    stdout: str, stderr: str, exit_code: int | None, options: Mapping[str, Any]
) -> AgentUsage:
    """Fold a Codex JSONL event stream into ``AgentUsage``, skipping unknown or malformed lines."""
    usage = AgentUsage()
    turns = in_tok = cached = out_tok = 0
    saw_usage = False
    pending_error: str | None = None  # last error not followed by a completed turn
    events = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        events += 1
        kind = event.get("type")
        if kind == "turn.completed":
            turns += 1
            pending_error = None
            u = event.get("usage")
            if isinstance(u, Mapping):
                saw_usage = True
                in_tok += _int(u.get("input_tokens")) or 0
                cached += _int(u.get("cached_input_tokens")) or 0
                out_tok += _int(u.get("output_tokens")) or 0
        elif kind == "item.completed":
            item = event.get("item")
            if isinstance(item, Mapping):
                item_type = item.get("type", item.get("item_type"))
                text = item.get("text")
                if item_type in _MESSAGE_ITEMS and isinstance(text, str):
                    usage.final_message = text
        elif kind in ("turn.failed", "error"):
            pending_error = _error_text(event)

    usage.turns = turns if events else None
    if saw_usage:
        # Stored as uncached input so input_tokens means the same thing across adapters.
        usage.input_tokens = max(in_tok - cached, 0)
        usage.cache_read_tokens = cached
        usage.output_tokens = out_tok
        usage.cost_usd = _cost(options, in_tok, cached, out_tok)

    if pending_error is not None:
        if _looks_like_infra(pending_error):
            usage.infra_error = _tail(pending_error)
        elif usage.final_message is None:
            usage.final_message = pending_error
    elif events == 0 and exit_code not in (0, None):
        detail = _tail(stderr) or _tail(stdout) or "no output"
        usage.infra_error = f"codex exited with code {exit_code} without JSON events: {detail}"
    elif exit_code not in (0, None) and turns == 0 and _looks_like_infra(stderr):
        usage.infra_error = _tail(stderr)
    return usage


class CodexAdapter(Adapter):
    """Runs ``codex exec --json`` with the prompt on stdin (``-`` positional)."""

    name = "codex"
    option_keys = frozenset(
        {"executable", "sandbox", "ignore_user_config", "bypass_sandbox", *_PRICES}
    )

    def validate(self, spec: AgentSpec) -> list[str]:
        problems = super().validate(spec)
        o = spec.options
        if spec.effort is not None and spec.effort not in EFFORTS:
            problems.append(
                f"effort {spec.effort!r} is not valid for codex "
                f"(valid: {', '.join(sorted(EFFORTS))})"
            )
        exe = o.get("executable", "codex")
        if not isinstance(exe, str) or not exe.strip():
            problems.append("option 'executable' must be a non-empty string")
        if "sandbox" in o and o["sandbox"] not in SANDBOXES:
            problems.append(f"option 'sandbox' must be one of {', '.join(sorted(SANDBOXES))}")
        problems += _check_bool(o, "ignore_user_config")
        problems += _check_bool(o, "bypass_sandbox")
        if o.get("bypass_sandbox") is True and "sandbox" in o:
            problems.append("options 'sandbox' and 'bypass_sandbox' are mutually exclusive")
        for key in _PRICES:
            if key in o and not (_is_number(o[key]) and o[key] >= 0):
                problems.append(f"option {key!r} must be a non-negative number")
        return problems

    def check_available(self, spec: AgentSpec) -> str | None:
        exe = spec.options.get("executable", "codex")
        if _resolve(exe) is None:
            return (
                f"codex: executable {exe!r} not found on PATH "
                "(install the Codex CLI or set [agent.options].executable)"
            )
        return None

    def build(self, ctx: TrialContext) -> AgentInvocation:
        spec, o = ctx.spec, ctx.spec.options
        exe = o.get("executable", "codex")
        argv = [
            _resolve(exe) or exe,
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--ephemeral",
            "-C",
            str(ctx.workspace),
        ]
        if o.get("bypass_sandbox"):
            argv.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            argv += ["--sandbox", o.get("sandbox", "workspace-write")]
        if spec.model:
            argv += ["-m", spec.model]
        if spec.effort:
            # Unquoted on purpose: Windows .cmd shims mangle embedded quotes, and codex
            # treats a value that is not valid TOML as a literal string.
            argv += ["-c", f"model_reasoning_effort={spec.effort}"]
        if o.get("ignore_user_config"):
            argv.append("--ignore-user-config")
        argv += list(spec.args)
        argv.append("-")  # read the prompt from stdin
        return AgentInvocation(argv=argv, env=dict(spec.env), stdin=ctx.prompt, cwd=ctx.workspace)

    def parse(self, ctx: TrialContext, result: ProcResult) -> AgentUsage:
        if result.start_error:
            return AgentUsage(infra_error=f"could not start codex: {result.start_error}")
        stdout = read_text(result.stdout_path, _STDOUT_LIMIT)
        stderr = read_text(result.stderr_path, 64 * 1024)
        exit_code = None if result.timed_out else result.exit_code
        try:
            return parse_events(stdout, stderr, exit_code, ctx.spec.options)
        except Exception as e:  # noqa: BLE001 - parse must never raise
            return AgentUsage(infra_error=f"could not parse codex output: {e}")
