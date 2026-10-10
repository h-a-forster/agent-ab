"""Adapter for Claude Code in print mode (``claude -p --output-format stream-json``)."""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Mapping
from typing import Any

from agent_ab.adapters.base import (
    Adapter,
    batch_argv_issue,
    check_batch_argv,
    probe_version,
    read_head,
    read_text,
)
from agent_ab.adapters.command import _check_bool, _is_number, _resolve
from agent_ab.model import AgentInvocation, AgentSpec, AgentUsage, ProcResult, TrialContext

EFFORTS: frozenset[str] = frozenset({"low", "medium", "high", "xhigh", "max"})
PERMISSION_MODES: frozenset[str] = frozenset(
    {"acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan"}
)
SETTING_SOURCES: frozenset[str] = frozenset({"user", "project", "local"})
SYSTEM_PROMPT_FILE = "append_system_prompt.md"

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
_HEAD_LIMIT = 1024 * 1024  # the init event is the first few events; stdout is read from the front
_TAIL = 500
INIT_FILE = "init.json"
_MAX_MODELS = 20
_MAX_LIST = 500
_MAX_TEXT = 200

# Fields of the init event that identify this machine or session rather than the setup.
_INIT_DROP = frozenset(
    {
        "cwd",
        "session_id",
        "uuid",
        "scratchpad_path",
        "messaging_socket_path",
        "startup_timing",
    }
)
_ABSOLUTE_PATH = re.compile(r"^(?:/|~[/\\]|\\\\|[A-Za-z]:[/\\])")


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


def _models(v: Any) -> list[str] | None:
    """Sorted model IDs from the result's ``modelUsage`` object (keys are model IDs)."""
    if not isinstance(v, Mapping):
        return None
    found = sorted({k[:_MAX_TEXT] for k in v if isinstance(k, str) and k})
    return found[:_MAX_MODELS] or None


def find_init(text: str) -> dict[str, Any] | None:
    """The ``system``/``init`` event of a stream-json transcript, or None."""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{") or '"init"' not in line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if (
            isinstance(event, dict)
            and event.get("type") == "system"
            and event.get("subtype") == "init"
        ):
            return event
    return None


def _is_path(v: Any) -> bool:
    return isinstance(v, str) and _ABSOLUTE_PATH.match(v) is not None


def scrub_init(value: Any) -> Any:
    """Copy of an init event without session identifiers, local paths and timings."""
    if isinstance(value, dict):
        return {
            k: scrub_init(v) for k, v in value.items() if k not in _INIT_DROP and not _is_path(v)
        }
    if isinstance(value, list):
        return [scrub_init(v) for v in value if not _is_path(v)]
    return value


def _names(items: Any) -> list[str]:
    """Names from a list of strings or ``{"name": ...}`` objects, sorted and bounded."""
    if not isinstance(items, list):
        return []
    names = {
        (i if isinstance(i, str) else i.get("name") if isinstance(i, Mapping) else None)
        for i in items
    }
    return sorted(n[:_MAX_TEXT] for n in names if isinstance(n, str) and n)[:_MAX_LIST]


def summarise_init(event: Mapping[str, Any]) -> dict[str, Any]:
    """The compact, comparable part of an init event, as stored on the trial record."""
    out: dict[str, Any] = {}
    for key, source in (
        ("model", "model"),
        ("claude_code_version", "claude_code_version"),
        ("permission_mode", "permissionMode"),
        ("api_key_source", "apiKeySource"),
    ):
        v = event.get(source)
        if isinstance(v, str) and v:
            out[key] = v[:_MAX_TEXT]
    out["tools"] = _names(event.get("tools"))
    servers = event.get("mcp_servers")
    out["mcp_servers"] = []
    if isinstance(servers, list):
        for item in servers:
            if isinstance(item, Mapping) and isinstance(item.get("name"), str):
                entry = {"name": item["name"][:_MAX_TEXT]}
                if isinstance(item.get("status"), str):
                    entry["status"] = item["status"][:_MAX_TEXT]
                out["mcp_servers"].append(entry)
        out["mcp_servers"] = sorted(out["mcp_servers"], key=lambda e: e["name"])[:_MAX_LIST]
    for key in ("plugins", "skills", "agents"):
        out[key] = _names(event.get(key))
    return out


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
    usage.models = _models(obj.get("modelUsage"))
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
    """Runs ``claude -p`` with the prompt on stdin.

    By default the output is ``stream-json``, whose first events include the init event
    (model, tools, MCP servers, plugins); its last line is the same result object that
    ``--output-format json`` prints.
    """

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
            "capture_init",
            "strict_mcp_config",
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
        problems += _check_bool(o, "capture_init")
        problems += _check_bool(o, "strict_mcp_config")
        return problems

    def check_available(self, spec: AgentSpec) -> str | None:
        exe = spec.options.get("executable", "claude")
        resolved = _resolve(exe)
        if resolved is None:
            return (
                f"claude-code: executable {exe!r} not found on PATH "
                "(install Claude Code or set [agent.options].executable)"
            )
        # The system-prompt file path is only known per attempt; build() checks it.
        issue = batch_argv_issue(self._argv(spec, resolved, None))
        return f"claude-code: {issue}" if issue else None

    def version(self, spec: AgentSpec) -> str | None:
        return probe_version(spec, "claude")  # prints e.g. "2.1.296 (Claude Code)"

    def _argv(self, spec: AgentSpec, exe: str, system_prompt_file: str | None) -> list[str]:
        o = spec.options
        argv = [exe, "-p", "--output-format"]
        # stream-json needs --verbose; it is what exposes the init event.
        argv += ["stream-json", "--verbose"] if o.get("capture_init", True) else ["json"]
        argv += [
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
            # Hidden from ``claude --help`` in recent releases but still accepted (unknown
            # options are rejected); passed through unchanged.
            argv += ["--max-turns", str(o["max_turns"])]
        if o.get("safe_mode"):
            argv.append("--safe-mode")
        if o.get("bare"):
            argv.append("--bare")
        if o.get("setting_sources") is not None:
            argv += ["--setting-sources", o["setting_sources"]]
        if o.get("strict_mcp_config", True):
            # Without --mcp-config this means no MCP servers, not even the user's own.
            argv.append("--strict-mcp-config")
        if system_prompt_file is not None:
            argv += ["--append-system-prompt-file", system_prompt_file]
        argv += list(spec.args)
        return argv

    def build(self, ctx: TrialContext) -> AgentInvocation:
        spec, o = ctx.spec, ctx.spec.options
        exe = o.get("executable", "claude")
        system_prompt_file = None
        if o.get("append_system_prompt") is not None:
            # Passed as a file: multi-line text does not survive a command line intact
            # (a Windows batch shim would cut it at the first newline).
            ctx.artifacts.mkdir(parents=True, exist_ok=True)
            path = ctx.artifacts / SYSTEM_PROMPT_FILE
            path.write_text(o["append_system_prompt"], encoding="utf-8", newline="")
            system_prompt_file = str(path)
        argv = self._argv(spec, _resolve(exe) or exe, system_prompt_file)
        check_batch_argv(argv)
        # The prompt goes on stdin: no argv length limits or Windows quoting pitfalls.
        return AgentInvocation(argv=argv, env=dict(spec.env), stdin=ctx.prompt, cwd=ctx.workspace)

    def parse(self, ctx: TrialContext, result: ProcResult) -> AgentUsage:
        if result.start_error:
            return AgentUsage(infra_error=f"could not start claude: {result.start_error}")
        stdout = read_text(result.stdout_path, _STDOUT_LIMIT)
        stderr = read_text(result.stderr_path, 64 * 1024)
        exit_code = None if result.timed_out else result.exit_code
        try:
            usage = parse_result_text(stdout, stderr, exit_code)
        except Exception as e:  # noqa: BLE001 - parse must never raise
            return AgentUsage(infra_error=f"could not parse claude output: {e}")
        if ctx.spec.options.get("capture_init", True):
            # Best effort: a missing init event leaves the fields unknown.
            with contextlib.suppress(Exception):
                self._capture_init(ctx, result, usage)
        return usage

    @staticmethod
    def _capture_init(ctx: TrialContext, result: ProcResult, usage: AgentUsage) -> None:
        # Read from the front: stdout is tail-limited above, and a long run would push the
        # init event out of the tail.
        event = find_init(read_head(result.stdout_path, _HEAD_LIMIT))
        if event is None:
            return
        ctx.artifacts.mkdir(parents=True, exist_ok=True)
        text = json.dumps(scrub_init(event), indent=2, ensure_ascii=False) + "\n"
        (ctx.artifacts / INIT_FILE).write_text(text, encoding="utf-8", newline="\n")
        usage.agent_init = summarise_init(scrub_init(event))
        usage.agent_version = usage.agent_init.get("claude_code_version")
