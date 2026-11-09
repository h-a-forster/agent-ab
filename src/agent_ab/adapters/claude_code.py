"""Adapter for Claude Code in print mode (``claude -p --output-format stream-json``)."""

from __future__ import annotations

import contextlib
import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
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

# Failures of the provider or the account, for runs that left no result to go by.
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

# ---- isolation (option ``isolation``, on by default)
#
# Claude Code reads user-level configuration from its config directory (``~/.claude``, or
# CLAUDE_CONFIG_DIR): settings, memory (CLAUDE.md, rules), auto memory, plugins and skills. It
# also loads CLAUDE.md files from every parent of its working directory and inherits the
# environment. An isolated trial gets an empty config directory beside its workspace, an
# allow-listed environment, and a check of its init event for memory loaded from elsewhere.

CONFIG_DIR_SUFFIX = ".claude-config"

# Passed through to an isolated agent (names compared case-insensitively). Everything else is
# dropped, e.g. what a parent Claude Code session sets (CLAUDECODE, CLAUDE_CODE_ENTRYPOINT,
# CLAUDE_CODE_SIMPLE, CLAUDE_CODE_GIT_BASH_PATH), CLAUDE_CONFIG_DIR, model overrides
# (ANTHROPIC_MODEL), Python environments (PYTHONHOME, PYTHONPATH, VIRTUAL_ENV) and unrelated
# secrets. Option ``pass_env`` adds names; ``[agent].env`` is always applied on top.
_ENV_ALLOW = frozenset(
    {
        # operating system and locale
        "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "OS",
        "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
        "USERNAME", "USERDOMAIN", "USER", "LOGNAME", "SHELL", "TERM", "LANG", "LANGUAGE", "TZ",
        "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "ALLUSERSPROFILE", "PUBLIC",
        "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES",
        "COMMONPROGRAMFILES(X86)", "COMMONPROGRAMW6432", "PSMODULEPATH",
        "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
        # network and certificates
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "NODE_EXTRA_CA_CERTS",
        "NODE_USE_SYSTEM_CA", "SSL_CERT_FILE", "SSL_CERT_DIR", "CLAUDE_CODE_CERT_STORE",
        "CLAUDE_CODE_CLIENT_CERT", "CLAUDE_CODE_CLIENT_KEY", "CLAUDE_CODE_CLIENT_KEY_PASSPHRASE",
        # credentials and API provider
        "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_PROFILE",
        "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_USE_MANTLE", "CLAUDE_CODE_USE_ANTHROPIC_AWS",
        "CLOUD_ML_REGION", "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT",
    }
)  # fmt: skip
_ENV_ALLOW_PREFIXES = (
    "LC_",
    "AWS_",
    "ANTHROPIC_VERTEX_",
    "ANTHROPIC_BEDROCK_",
    "ANTHROPIC_FOUNDRY_",
    "ANTHROPIC_AWS_",
    "VERTEX_REGION_",
)
# An isolated agent has no saved login, so it needs one of these. --bare reads neither an OAuth
# token nor a profile.
_AUTH_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_PROFILE",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_MANTLE",
    "CLAUDE_CODE_USE_ANTHROPIC_AWS",
)
_BARE_UNREAD = frozenset({"CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_PROFILE"})
# What Claude Code loads from the parents of its working directory, whatever --setting-sources
# says (checked on 2.1.308); in the home directory, these ``.claude`` entries are the user's own.
_ANCESTOR_FILES = (
    "CLAUDE.md",
    "CLAUDE.local.md",
    "AGENTS.md",
    ".claude/CLAUDE.md",
    ".claude/rules",
    ".claude/skills",
    ".claude/agents",
    ".claude/commands",
)
_INSTRUCTION_NAMES = frozenset({"claude.md", "claude.local.md", "agents.md"})


def config_dir(workspace: Path) -> Path:
    """The private config directory of an isolated trial: a sibling of its workspace."""
    return workspace.with_name(workspace.name + CONFIG_DIR_SUFFIX)


def isolated_env(environ: Mapping[str, str], extra: Iterable[str] = ()) -> dict[str, str]:
    """The allow-listed part of ``environ``, plus the names in ``extra``.

    When VIRTUAL_ENV is set (``uv run``, an activated venv), its ``bin``/``Scripts`` directory
    is also taken off PATH, so the agent's ``python`` is not agent-ab's own interpreter.
    """
    allow = _ENV_ALLOW | {name.upper() for name in extra}
    env = {
        k: v
        for k, v in environ.items()
        if k.upper() in allow or k.upper().startswith(_ENV_ALLOW_PREFIXES)
    }
    venv = next((v for k, v in environ.items() if k.upper() == "VIRTUAL_ENV" and v), None)
    path_key = next((k for k in env if k.upper() == "PATH"), None)
    if venv and path_key and "VIRTUAL_ENV" not in allow:
        drop = {_norm(os.path.join(venv, d)) for d in ("bin", "Scripts")}
        parts = env[path_key].split(os.pathsep)
        env[path_key] = os.pathsep.join(p for p in parts if p and _norm(p) not in drop)
    return env


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _inside(path: str, root: str) -> bool:
    p, r = _norm(path), _norm(root)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def _describe(path: str) -> str:
    """A path reduced to its last component and whether it is in the home directory, so records
    stay free of user names (which also appear in encoded project directory names)."""
    name = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    try:
        home = str(Path.home())
    except (RuntimeError, OSError):
        home = None
    return f"~/.../{name}" if home and _inside(path, home) else f".../{name}"


def config_leaks(event: Mapping[str, Any], allowed: Sequence[Path]) -> list[str]:
    """Memory and instruction files the init event shows were loaded from outside ``allowed``.

    Looks at every path under ``memory_paths`` and every path anywhere in the event that names
    a CLAUDE.md, CLAUDE.local.md, AGENTS.md or ``.claude/rules`` entry. Returns sorted entries
    such as ``"memory_paths.auto: ~/.../memory"``. The event does not list every loaded file
    (Claude Code 2.1.308 listed only the auto-memory directory), so an empty result is not
    proof that nothing else was loaded.
    """
    roots = {str(r) for r in allowed} | {os.path.realpath(r) for r in allowed}
    found: set[str] = set()

    def walk(value: Any, key: str) -> None:
        if isinstance(value, Mapping):
            for k, v in value.items():
                walk(v, f"{key}.{k}" if key else str(k))
        elif isinstance(value, list):
            for v in value:
                walk(v, key)
        elif _is_path(value):
            name = value.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()
            memory = key == "memory_paths" or key.startswith("memory_paths.")
            rules = "/.claude/rules" in value.replace("\\", "/").lower()
            if (memory or rules or name in _INSTRUCTION_NAMES) and not any(
                _inside(value, r) for r in roots
            ):
                found.add(f"{key}: {_describe(value)}"[:_MAX_TEXT])

    walk(event, "")
    return sorted(found)[:_MAX_LIST]


def instruction_files_above(root: Path) -> list[Path]:
    """Instruction files and agent definitions Claude Code would load from ``root`` and its
    parents."""
    root = Path(root).resolve()
    return [d / rel for d in (root, *root.parents) for rel in _ANCESTOR_FILES if (d / rel).exists()]


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
    died = exit_code not in (0, None)
    if obj is None or (died and obj.get("type") not in ("result", None)):
        # No result event: the CLI died, whatever the last event or its stderr says.
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

    # By structure, never by wording: the text of a failure varies by arm, and the agent writes
    # some of it. A failed run blames the agent only through a turn or budget limit or a status
    # that blames the request. Anything else cannot be told apart from a machine or provider
    # failure, so it does not count against the arm: it is retried, then excluded and reported.
    failed = obj.get("is_error") is True or (died and obj.get("is_error") is not False)
    status = obj.get("api_error_status")
    if failed and subtype not in _AGENT_SUBTYPES and (_infra_status(status) or status is None):
        message = usage.final_message or ""
        detail = _tail(message, _TAIL - 20) or _tail(stderr, _TAIL - 20) or str(subtype)
        usage.infra_error = f"API error {status}: {detail}" if status is not None else detail
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
            "isolation",
            "pass_env",
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
        problems += _check_bool(o, "isolation")
        isolated = o.get("isolation", True) is True
        if "pass_env" in o:
            names = o["pass_env"]
            if not isinstance(names, list) or not all(
                isinstance(n, str) and n.strip() and "=" not in n for n in names
            ):
                problems.append("option 'pass_env' must be a list of environment variable names")
            elif not isolated:
                problems.append("option 'pass_env' only applies with isolation = true")
        if isolated:
            if o.get("capture_init", True) is False:
                problems.append(
                    "isolation = true needs capture_init = true: the init event is how leaks "
                    "of user-level memory are detected"
                )
            if any(k.upper() == "CLAUDE_CONFIG_DIR" for k in spec.env):
                problems.append(
                    "env sets CLAUDE_CONFIG_DIR, which isolation replaces with an empty "
                    "directory per trial; set isolation = false to use your own"
                )
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
        if issue:
            return f"claude-code: {issue}"
        return self._auth_problem(spec) if spec.options.get("isolation", True) else None

    @staticmethod
    def _auth_problem(spec: AgentSpec) -> str | None:
        env = {k.upper(): v for k, v in isolated_env(os.environ).items() if v}
        env.update({k.upper(): v for k, v in spec.env.items() if v})
        usable = [n for n in _AUTH_ENV if not (spec.options.get("bare") and n in _BARE_UNREAD)]
        if any(env.get(n) for n in usable):
            return None
        return (
            "claude-code: isolation (on by default) gives each trial an empty config "
            "directory, so the agent cannot use your saved login. Set one of "
            f"{', '.join(usable)} in the environment or in [agent.env] (`claude setup-token` "
            "prints a CLAUDE_CODE_OAUTH_TOKEN), or set isolation = false"
        )

    def check_workspace_root(self, spec: AgentSpec, root: Path) -> str | None:
        if not spec.options.get("isolation", True):
            return None
        found = instruction_files_above(root)
        if not found:
            return None
        return (
            "claude-code: Claude Code would load these from the parents of the workspaces "
            f"under {root}: {', '.join(str(f) for f in found)}. Move them, set "
            "workspace_root elsewhere, or set isolation = false"
        )

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
        files = [Path(system_prompt_file)] if system_prompt_file is not None else []
        inv = AgentInvocation(
            argv=argv, env=dict(spec.env), stdin=ctx.prompt, cwd=ctx.workspace,
            instruction_files=files,
        )  # fmt: skip
        if o.get("isolation", True):
            config = config_dir(ctx.workspace)
            config.mkdir()
            inv.base_env = isolated_env(os.environ, o.get("pass_env", ()))
            inv.env["CLAUDE_CONFIG_DIR"] = str(config)
            inv.temp_dirs.append(config)
        return inv

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
        usage.leak_check = "unverified"  # until the check below has actually run
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
        # From the raw event: init.json and the summary have no absolute paths left to check.
        isolated = ctx.spec.options.get("isolation", True)
        allowed = [ctx.workspace, config_dir(ctx.workspace)] if isolated else [ctx.workspace]
        leaks = config_leaks(event, allowed)
        usage.leak_check = "leaked" if leaks else "clean"
        if leaks and isolated and usage.infra_error is None:
            shown = "; ".join(leaks[:5]) + ("; ..." if len(leaks) > 5 else "")
            usage.infra_error = (
                "isolation breach: the agent loaded memory or instructions from outside its "
                f"workspace and private config directory ({shown}); see agent.stdout"
            )
            usage.isolation_breach = True
        usage.agent_init = {**summarise_init(scrub_init(event)), "config_leaks": leaks}
        usage.agent_version = usage.agent_init.get("claude_code_version")
        ctx.artifacts.mkdir(parents=True, exist_ok=True)
        text = json.dumps(scrub_init(event), indent=2, ensure_ascii=False) + "\n"
        (ctx.artifacts / INIT_FILE).write_text(text, encoding="utf-8", newline="\n")
