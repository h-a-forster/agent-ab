"""Adapter for Claude Code in print mode (``claude -p --output-format json``)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from agent_ab.adapters.base import Adapter, read_text
from agent_ab.adapters.command import _check_bool, _is_number, _resolve
from agent_ab.model import AgentInvocation, AgentSpec, AgentUsage, ProcResult, TrialContext

EFFORTS: frozenset[str] = frozenset({"low", "medium", "high", "xhigh", "max"})
PERMISSION_MODES: frozenset[str] = frozenset(
    {"acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan"}
)
SETTING_SOURCES: frozenset[str] = frozenset({"user", "project", "local"})

# Failures of the provider or the account rather than of the configuration under test.
# Only consulted when a run already failed, so a successful answer that mentions "429" is safe.
_INFRA = re.compile(
    r"authentication|invalid api key|not logged in|/login|oauth token|unauthori[sz]ed"
    r"|rate[ _-]?limit|too many requests|\b429\b|overloaded|\b529\b"
    r"|econnreset|econnrefused|etimedout|enotfound|socket hang up|network error"
    r"|connection (?:error|reset|refused)|credit balance|usage limit|quota",
    re.IGNORECASE,
)

# Agent-side failures: the agent ran out of turns or budget, which is a legitimate outcome.
_AGENT_SUBTYPES = frozenset({"error_max_turns", "error_max_budget_usd"})

# ``api_error_status`` values that blame the account or provider: auth, no access, unknown
# model (404, which costs nothing and should not count against the arm), rate limits, outages.
_INFRA_STATUSES = frozenset({401, 403, 404, 408, 429})

_STDOUT_LIMIT = 16 * 1024 * 1024
_TAIL = 500


def _looks_like_infra(text: str) -> bool:
    return bool(text) and _INFRA.search(text) is not None


def _tail(text: str, n: int = _TAIL) -> str:
    text = text.strip()
    return text[-n:]


def _json_objects(text: str) -> list[dict[str, Any]]:
    """Every JSON object found in ``text``: the whole text, then line by line, in order."""
    stripped = text.strip()
    if not stripped:
        return []
    try:
        whole = json.loads(stripped)
    except ValueError:
        pass
    else:
        return [whole] if isinstance(whole, dict) else []
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        start = line.find("{")
        if start < 0:
            continue
        try:
            obj, _ = decoder.raw_decode(line, start)
        except ValueError:
            # A pretty-printed object may span the rest of the output.
            if line.lstrip().startswith("{"):
                rest = "\n".join(lines[i:])
                try:
                    obj, _ = decoder.raw_decode(rest, rest.find("{"))
                except ValueError:
                    continue
            else:
                continue
        if isinstance(obj, dict):
            found.append(obj)
    return found


def _pick_result(objects: list[dict[str, Any]]) -> dict[str, Any] | None:
    for obj in reversed(objects):
        if obj.get("type") == "result":
            return obj
    return objects[-1] if objects else None


def _infra_status(v: Any) -> bool:
    status = _int(v)
    return status is not None and (status in _INFRA_STATUSES or status >= 500)


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _format_number(v: float | int) -> str:
    if isinstance(v, int):
        return str(v)
    return f"{v:.6f}".rstrip("0").rstrip(".")


def parse_result_text(stdout: str, stderr: str, exit_code: int | None) -> AgentUsage:
    """Map Claude Code's JSON result (possibly preceded by log lines) onto ``AgentUsage``."""
    usage = AgentUsage()
    obj = _pick_result(_json_objects(stdout))
    if obj is None:
        if exit_code not in (0, None):
            detail = _tail(stderr) or _tail(stdout) or "no output"
            usage.infra_error = (
                f"claude exited with code {exit_code} without a JSON result: {detail}"
            )
        elif _looks_like_infra(stderr):
            usage.infra_error = _tail(stderr)
        return usage

    cost = obj.get("total_cost_usd")
    if _is_number(cost) and cost >= 0:
        usage.cost_usd = float(cost)
    usage.turns = _int(obj.get("num_turns"))
    tokens = obj.get("usage")
    if isinstance(tokens, Mapping):
        usage.input_tokens = _int(tokens.get("input_tokens"))
        usage.output_tokens = _int(tokens.get("output_tokens"))
        usage.cache_read_tokens = _int(tokens.get("cache_read_input_tokens"))
        usage.cache_write_tokens = _int(tokens.get("cache_creation_input_tokens"))
    text = obj.get("result")
    if isinstance(text, str):
        usage.final_message = text
    subtype = obj.get("subtype")

    failed = obj.get("is_error") is True or exit_code not in (0, None)
    if failed and subtype not in _AGENT_SUBTYPES:
        message = usage.final_message or ""
        status = obj.get("api_error_status")
        if _infra_status(status):
            usage.infra_error = f"API error {status}: {_tail(message, _TAIL - 20)}"
        elif _looks_like_infra(message):
            usage.infra_error = _tail(message)
        elif _looks_like_infra(stderr):
            usage.infra_error = _tail(stderr)
    if usage.final_message is None and isinstance(subtype, str) and subtype.startswith("error"):
        usage.final_message = subtype
    return usage


class ClaudeCodeAdapter(Adapter):
    """Runs ``claude -p --output-format json`` with the prompt on stdin."""

    name = "claude-code"
    option_keys = frozenset(
        {
            "executable",
            "permission_mode",
            "max_budget_usd",
            "max_turns",
            "safe_mode",
            "bare",
            "setting_sources",
            "append_system_prompt",
        }
    )

    def validate(self, spec: AgentSpec) -> list[str]:
        problems = super().validate(spec)
        o = spec.options
        if spec.effort is not None and spec.effort not in EFFORTS:
            problems.append(
                f"effort {spec.effort!r} is not valid for claude-code "
                f"(valid: {', '.join(sorted(EFFORTS))})"
            )
        exe = o.get("executable", "claude")
        if not isinstance(exe, str) or not exe.strip():
            problems.append("option 'executable' must be a non-empty string")
        mode = o.get("permission_mode", "bypassPermissions")
        if mode not in PERMISSION_MODES:
            problems.append(
                f"option 'permission_mode' must be one of {', '.join(sorted(PERMISSION_MODES))}"
            )
        budget = o.get("max_budget_usd")
        if "max_budget_usd" in o and not (_is_number(budget) and budget > 0):
            problems.append("option 'max_budget_usd' must be a positive number")
        if "max_turns" in o:
            turns = o["max_turns"]
            if not (isinstance(turns, int) and not isinstance(turns, bool) and turns > 0):
                problems.append("option 'max_turns' must be a positive integer")
        problems += _check_bool(o, "safe_mode")
        problems += _check_bool(o, "bare")
        if "setting_sources" in o:
            src = o["setting_sources"]
            parts = {p.strip() for p in src.split(",")} - {""} if isinstance(src, str) else None
            if parts is None or not parts <= SETTING_SOURCES:
                problems.append(
                    "option 'setting_sources' must be a comma-separated string of "
                    "user, project, local (or empty)"
                )
        if "append_system_prompt" in o and not isinstance(o["append_system_prompt"], str):
            problems.append("option 'append_system_prompt' must be a string")
        return problems

    def check_available(self, spec: AgentSpec) -> str | None:
        exe = spec.options.get("executable", "claude")
        if _resolve(exe) is None:
            return (
                f"claude-code: executable {exe!r} not found on PATH "
                "(install Claude Code or set [agent.options].executable)"
            )
        return None

    def build(self, ctx: TrialContext) -> AgentInvocation:
        spec, o = ctx.spec, ctx.spec.options
        exe = o.get("executable", "claude")
        argv = [
            _resolve(exe) or exe,
            "-p",
            "--output-format",
            "json",
            "--no-session-persistence",
            "--permission-mode",
            o.get("permission_mode", "bypassPermissions"),
        ]
        if spec.model:
            argv += ["--model", spec.model]
        if spec.effort:
            argv += ["--effort", spec.effort]
        if o.get("max_budget_usd") is not None:
            argv += ["--max-budget-usd", _format_number(o["max_budget_usd"])]
        if o.get("max_turns") is not None:
            argv += ["--max-turns", str(o["max_turns"])]
        if o.get("safe_mode"):
            argv.append("--safe-mode")
        if o.get("bare"):
            argv.append("--bare")
        if o.get("setting_sources") is not None:
            argv += ["--setting-sources", o["setting_sources"]]
        if o.get("append_system_prompt") is not None:
            argv += ["--append-system-prompt", o["append_system_prompt"]]
        argv += list(spec.args)
        # The prompt goes on stdin: no argv length limits or Windows quoting pitfalls.
        return AgentInvocation(argv=argv, env=dict(spec.env), stdin=ctx.prompt, cwd=ctx.workspace)

    def parse(self, ctx: TrialContext, result: ProcResult) -> AgentUsage:
        if result.start_error:
            return AgentUsage(infra_error=f"could not start claude: {result.start_error}")
        stdout = read_text(result.stdout_path, _STDOUT_LIMIT)
        stderr = read_text(result.stderr_path, 64 * 1024)
        exit_code = None if result.timed_out else result.exit_code
        try:
            return parse_result_text(stdout, stderr, exit_code)
        except Exception as e:  # noqa: BLE001 - parse must never raise
            return AgentUsage(infra_error=f"could not parse claude output: {e}")
