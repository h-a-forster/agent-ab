"""Adapter for the Codex CLI in non-interactive mode (``codex exec --json``)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from agent_ab.adapters.base import Adapter, batch_argv_issue, check_batch_argv, read_text
from agent_ab.adapters.claude_code import _int, _looks_like_infra, _tail
from agent_ab.adapters.command import _check_bool, _is_number, _resolve
from agent_ab.model import AgentInvocation, AgentSpec, AgentUsage, ProcResult, TrialContext

SANDBOXES: frozenset[str] = frozenset({"read-only", "workspace-write", "danger-full-access"})
# Which levels a model accepts varies; this is the union across current and older models.
EFFORTS: frozenset[str] = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
)
_PRICES = ("price_input_per_mtok", "price_cached_input_per_mtok", "price_output_per_mtok")
_MESSAGE_ITEMS = frozenset({"agent_message", "assistant_message"})  # older releases used the latter

_STDOUT_LIMIT = 16 * 1024 * 1024

# The configured model cannot be used at all (e.g. not available to a ChatGPT-plan account):
# a setup problem that should be reported, not scored as the arm failing the task.
_MODEL_UNAVAILABLE = re.compile(
    r"\bmodel\b[^\n]{0,120}?\b(?:is not supported|not found|does not exist)|model_not_found",
    re.IGNORECASE,
)
# The sandbox could not start any process (seen with ``[windows] sandbox = "elevated"`` when
# no one can approve the elevated setup helper): the agent could not act at all.
_SANDBOX_BROKEN = re.compile(
    r"windows sandbox failed|failed to create unified exec process|helper_unknown_error"
    r"|setup refresh had errors|orchestrator_helper",
    re.IGNORECASE,
)


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
    turns = in_tok = cached = cache_write = out_tok = 0
    saw_usage = saw_cache_write = False
    commands_ok = False  # any command the agent ran exited 0
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
                written = _int(u.get("cache_write_input_tokens"))
                if written is not None:
                    saw_cache_write = True
                    cache_write += written
        elif kind == "item.completed":
            item = event.get("item")
            if isinstance(item, Mapping):
                item_type = item.get("type", item.get("item_type"))
                text = item.get("text")
                if item_type in _MESSAGE_ITEMS and isinstance(text, str):
                    usage.final_message = text
                elif item_type == "command_execution" and item.get("exit_code") == 0:
                    commands_ok = True
        elif kind in ("turn.failed", "error"):
            pending_error = _error_text(event)

    usage.turns = turns if events else None
    if saw_usage:
        # Stored as uncached input so input_tokens means the same thing across adapters.
        usage.input_tokens = max(in_tok - cached, 0)
        usage.cache_read_tokens = cached
        usage.output_tokens = out_tok
        usage.cost_usd = _cost(options, in_tok, cached, out_tok)
        if saw_cache_write:
            # Recorded as reported. Only zeros have been observed, so whether input_tokens
            # already includes these (and how they are billed) is unverified.
            usage.cache_write_tokens = cache_write

    if pending_error is not None:
        if _looks_like_infra(pending_error) or _MODEL_UNAVAILABLE.search(pending_error):
            usage.infra_error = _tail(pending_error)
        elif usage.final_message is None:
            usage.final_message = pending_error
    elif events == 0 and exit_code not in (0, None):
        detail = _tail(stderr) or _tail(stdout) or "no output"
        usage.infra_error = f"codex exited with code {exit_code} without JSON events: {detail}"
    elif exit_code not in (0, None) and turns == 0 and _looks_like_infra(stderr):
        usage.infra_error = _tail(stderr)
    if usage.infra_error is None and not commands_ok:
        broken = _SANDBOX_BROKEN.search(stderr)
        if broken:
            line = next(ln for ln in stderr.splitlines() if _SANDBOX_BROKEN.search(ln))
            usage.infra_error = "codex sandbox could not run commands: " + _tail(line, 400)
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
        resolved = _resolve(exe)
        if resolved is None:
            return (
                f"codex: executable {exe!r} not found on PATH "
                "(install the Codex CLI or set [agent.options].executable)"
            )
        # The workspace path is only known per attempt; build() checks it.
        issue = batch_argv_issue(self._argv(spec, resolved, None))
        return f"codex: {issue}" if issue else None

    def _argv(self, spec: AgentSpec, exe: str, workspace: str | None) -> list[str]:
        o = spec.options
        argv = [exe, "exec", "--json", "--skip-git-repo-check", "--ephemeral"]
        if workspace is not None:
            argv += ["-C", workspace]
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
        return argv

    def build(self, ctx: TrialContext) -> AgentInvocation:
        spec = ctx.spec
        exe = spec.options.get("executable", "codex")
        argv = self._argv(spec, _resolve(exe) or exe, str(ctx.workspace))
        check_batch_argv(argv)
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
