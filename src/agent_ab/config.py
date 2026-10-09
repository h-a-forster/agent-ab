"""Load and validate experiment and task configuration (TOML), and fingerprint it.

Validation is deliberately strict: a typo in a config file should fail before any trial runs
(and spends money), with a message naming the file and key path of the problem.
"""

from __future__ import annotations

import copy
import datetime as _dt
import fnmatch
import glob
import hashlib
import json
import math
import os
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import fields, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from agent_ab.adapters import get_adapter
from agent_ab.errors import ConfigError
from agent_ab.model import AgentSpec, Arm, Command, Experiment, Task

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: Placeholders allowed in task ``check``/``setup`` commands.
TASK_PLACEHOLDERS = frozenset({"python", "workspace"})
#: Placeholders allowed in the ``command`` adapter's argv template.
COMMAND_PLACEHOLDERS = frozenset(
    {"prompt_file", "prompt", "workspace", "artifacts", "model", "effort", "python", "seed"}
)

# Never part of a task's identity: caches and VCS metadata differ between machines.
_IGNORED_NAMES = frozenset({"__pycache__", ".git"})
_IGNORED_SUFFIXES = (".pyc",)

_EXPERIMENT_KEYS = frozenset(
    {
        "name", "description", "tasks", "exclude_tasks", "repeats", "jobs", "seed", "budget_usd",
        "timeout_s", "check_timeout_s", "max_retries", "timeout_is_failure", "baseline",
        "keep_workspaces", "workspace_root", "agent", "arms",
    }
)
_AGENT_KEYS = frozenset({"adapter", "model", "effort", "args", "env", "command", "options"})
_ARM_KEYS = frozenset(
    {"name", "description", "prompt_prefix", "prompt_suffix", "overlay", "remove", "agent"}
)
_TASK_KEYS = frozenset(
    {"prompt", "prompt_file", "check", "setup", "timeout_s", "check_timeout_s", "tags"}
)

# Settings that may legitimately change between sessions of one run, so they stay out of the
# fingerprint. Arm descriptions are prose and do not affect behaviour either.
_VOLATILE_KEYS = (
    "jobs", "keep_workspaces", "workspace_root", "budget_usd", "description", "fingerprint",
    "config",
)

_MISSING: Any = object()


# --------------------------------------------------------------------------- typed TOML access


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "table"
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return "date/time"
    return type(value).__name__


def _short(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


class _Table:
    """Typed access to one TOML table; every error names the file and the key path."""

    def __init__(self, data: dict[str, Any], file: str, path: str = ""):
        self.data = data
        self.file = file
        self.path = path

    def key_path(self, key: str | None = None) -> str:
        if key is None:
            return self.path
        if key.startswith("["):
            return f"{self.path}{key}"
        return f"{self.path}.{key}" if self.path else key

    def where(self, key: str | None = None) -> str:
        path = self.key_path(key)
        return f"{self.file}: {path}" if path else self.file

    def error(self, message: str, key: str | None = None) -> ConfigError:
        return ConfigError(message, self.where(key))

    def wrong_type(self, key: str, expected: str, value: Any) -> ConfigError:
        return self.error(f"expected {expected}, got {_type_name(value)} {_short(value)}", key)

    def child(self, data: dict[str, Any], key: str) -> _Table:
        return _Table(data, self.file, self.key_path(key))

    def reject_unknown(self, allowed: frozenset[str]) -> None:
        for key in self.data:
            if key not in allowed:
                names = ", ".join(sorted(allowed))
                raise self.error(f"unknown key {key!r} (allowed: {names})", key)

    def raw(self, key: str, required: bool = False) -> Any:
        if key in self.data:
            return self.data[key]
        if required:
            raise self.error(f"missing required key {key!r}", key)
        return _MISSING

    def string(
        self, key: str, default: Any = None, *, required: bool = False, nonempty: bool = False
    ) -> Any:
        value = self.raw(key, required)
        if value is _MISSING:
            return default
        if not isinstance(value, str):
            raise self.wrong_type(key, "a string", value)
        if nonempty and not value.strip():
            raise self.error("must not be empty", key)
        return value

    def integer(self, key: str, default: int, *, minimum: int | None = None) -> int:
        value = self.raw(key)
        if value is _MISSING:
            return default
        # bool is an int subclass; `repeats = true` is a mistake, not 1.
        if isinstance(value, bool) or not isinstance(value, int):
            raise self.wrong_type(key, "an integer", value)
        if minimum is not None and value < minimum:
            raise self.error(f"must be >= {minimum}, got {value}", key)
        return value

    def number(self, key: str, default: float | None) -> float | None:
        """A finite number > 0 (all numeric settings are durations or amounts)."""
        value = self.raw(key)
        if value is _MISSING:
            return default
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise self.wrong_type(key, "a number", value)
        if not math.isfinite(value):
            raise self.error(f"must be a finite number, got {value}", key)
        if value <= 0:
            raise self.error(f"must be > 0, got {value}", key)
        return float(value)

    def boolean(self, key: str, default: bool) -> bool:
        value = self.raw(key)
        if value is _MISSING:
            return default
        if not isinstance(value, bool):
            raise self.wrong_type(key, "true or false", value)
        return value

    def strings(
        self, key: str, default: tuple[str, ...] = (), *, required: bool = False
    ) -> tuple[str, ...]:
        value = self.raw(key, required)
        if value is _MISSING:
            return default
        if not isinstance(value, list):
            raise self.wrong_type(key, "an array of strings", value)
        for i, item in enumerate(value):
            if not isinstance(item, str):
                raise self.wrong_type(f"{key}[{i}]", "a string", item)
        return tuple(value)

    def table(self, key: str) -> _Table | None:
        value = self.raw(key)
        if value is _MISSING:
            return None
        if not isinstance(value, dict):
            raise self.wrong_type(key, "a table", value)
        return self.child(value, key)


# --------------------------------------------------------------------------- placeholders

_TOKEN_RE = re.compile(r"\{\{|\}\}|\{([^{}]*)\}|[{}]")


def expand_placeholders(template: str, values: Mapping[str, str]) -> str:
    """Replace ``{name}`` with ``values[name]``; ``{{`` and ``}}`` are literal braces.

    Raises ``ConfigError`` for an unknown placeholder or an unmatched brace, so typos never
    reach a subprocess as literal text.
    """

    def substitute(match: re.Match[str]) -> str:
        token = match.group(0)
        if token == "{{":
            return "{"
        if token == "}}":
            return "}"
        name = match.group(1)
        if name is None:
            raise ConfigError(
                f"unmatched {token!r} in {template!r} (write {token * 2!r} for a literal brace)"
            )
        if name not in values:
            known = ", ".join("{" + k + "}" for k in sorted(values)) or "none"
            raise ConfigError(f"unknown placeholder {{{name}}} in {template!r} (known: {known})")
        return str(values[name])

    return _TOKEN_RE.sub(substitute, template)


def _check_template(template: str, allowed: frozenset[str], where: str) -> None:
    try:
        expand_placeholders(template, dict.fromkeys(allowed, "x"))
    except ConfigError as e:
        raise ConfigError(str(e), where) from None


def _command(t: _Table, key: str, *, required: bool) -> Command | None:
    value = t.raw(key, required)
    if value is _MISSING:
        return None
    if isinstance(value, str):
        if not value.strip():
            raise t.error("must not be empty", key)
        _check_template(value, TASK_PLACEHOLDERS, t.where(key))
        return value
    if not isinstance(value, list):
        raise t.wrong_type(key, "a shell string or an array of strings", value)
    if not value:
        raise t.error("must not be an empty array", key)
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise t.wrong_type(f"{key}[{i}]", "a string", item)
        _check_template(item, TASK_PLACEHOLDERS, t.where(f"{key}[{i}]"))
    if not value[0].strip():
        raise t.error("the program (first element) must not be empty", f"{key}[0]")
    return tuple(value)


# --------------------------------------------------------------------------- files


def _read_toml(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise ConfigError(f"file not found: {path}", label) from None
    except OSError as e:
        raise ConfigError(f"cannot read {path}: {e.strerror or e}", label) from None
    try:
        # utf-8-sig: editors on Windows sometimes prepend a BOM, which tomllib rejects.
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ConfigError(f"not valid UTF-8 (byte {e.start})", label) from None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML: {e}", label) from None


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _optional_dir(path: Path, label: str) -> Path | None:
    if not path.exists():
        return None
    if not path.is_dir():
        raise ConfigError(f"{path.name!r} must be a directory", label)
    return path


def _safe_relpath(value: str, t: _Table, key: str) -> str:
    """Normalise a relative path that must stay inside its base directory (posix form)."""
    if not value.strip():
        raise t.error("must not be empty", key)
    win = PureWindowsPath(value)
    # Check both flavours so a config is rejected the same way on every OS.
    if PurePosixPath(value).is_absolute() or win.is_absolute() or win.drive or value[0] in "/\\":
        raise t.error(f"must be a relative path, got {value!r}", key)
    parts = [p for p in re.split(r"[\\/]", value) if p not in ("", ".")]
    if ".." in parts:
        raise t.error(f"must not contain '..', got {value!r}", key)
    if not parts:
        raise t.error(f"must name a path below the base directory, got {value!r}", key)
    return "/".join(parts)


def _check_values(value: Any, t: _Table, key: str) -> None:
    """Reject non-finite floats anywhere inside an options value (they break JSON output)."""
    if isinstance(value, float) and not math.isfinite(value):
        raise t.error(f"must be a finite number, got {value}", key)
    if isinstance(value, list):
        for i, item in enumerate(value):
            _check_values(item, t, f"{key}[{i}]")
    elif isinstance(value, dict):
        for k, item in value.items():
            _check_values(item, t, f"{key}.{k}")


# --------------------------------------------------------------------------- tasks


def load_task(task_dir: Path) -> Task:
    """Load ``<task_dir>/task.toml``; the task id is the directory name."""
    task_dir = Path(task_dir).expanduser().resolve()
    return _load_task(task_dir, f"{task_dir.name}/task.toml")


def _load_task(task_dir: Path, label: str) -> Task:
    task_id = task_dir.name
    if not ID_RE.match(task_id):
        raise ConfigError(
            f"invalid task id {task_id!r}: directory names must match {ID_RE.pattern}", label
        )
    t = _Table(_read_toml(task_dir / "task.toml", label), label)
    t.reject_unknown(_TASK_KEYS)

    if "prompt" in t.data and "prompt_file" in t.data:
        raise t.error("set either 'prompt' or 'prompt_file', not both")
    if "prompt" in t.data:
        key = "prompt"
        prompt = t.string("prompt")
    elif "prompt_file" in t.data:
        key = "prompt_file"
        rel = t.string("prompt_file", nonempty=True)
        prompt_path = (task_dir / rel).resolve()
        if not prompt_path.is_relative_to(task_dir):
            raise t.error(f"must stay inside the task directory, got {rel!r}", key)
        if not prompt_path.is_file():
            raise t.error(f"file not found: {rel}", key)
        try:
            prompt = prompt_path.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError:
            raise t.error(f"{rel} is not valid UTF-8", key) from None
        except OSError as e:
            raise t.error(f"cannot read {rel}: {e.strerror or e}", key) from None
    else:
        raise t.error("missing required key 'prompt' (or 'prompt_file')")
    if not prompt.strip():
        raise t.error("prompt is empty", key)

    check = _command(t, "check", required=True)
    assert check is not None
    return Task(
        id=task_id,
        path=task_dir,
        prompt=prompt,
        check=check,
        repo=_optional_dir(task_dir / "repo", label),
        checks=_optional_dir(task_dir / "checks", label),
        solution=_optional_dir(task_dir / "solution", label),
        setup=_command(t, "setup", required=False),
        timeout_s=t.number("timeout_s", None),
        check_timeout_s=t.number("check_timeout_s", None),
        tags=t.strings("tags"),
    )


def _discover_tasks(t: _Table, root: Path, select: Sequence[str] | None) -> list[tuple[str, Path]]:
    patterns = t.strings("tasks", required=True)
    if not patterns:
        raise t.error("must list at least one glob", "tasks")
    excludes = t.strings("exclude_tasks")

    found: dict[str, Path] = {}
    for i, pattern in enumerate(patterns):
        key = f"tasks[{i}]"
        if not pattern.strip():
            raise t.error("must not be empty", key)
        full = pattern if os.path.isabs(pattern) else os.path.join(glob.escape(str(root)), pattern)
        is_glob = any(c in pattern for c in "*?[")
        matches = sorted(glob.glob(full, recursive=True))
        if not is_glob and not (matches and (Path(matches[0]) / "task.toml").is_file()):
            raise t.error(f"{pattern!r} is not a task directory (no task.toml)", key)
        for match in matches:
            path = Path(match).resolve()
            if not (path / "task.toml").is_file():
                continue
            if not ID_RE.match(path.name):
                raise t.error(
                    f"invalid task id {path.name!r} ({_rel(path, root)}): "
                    f"directory names must match {ID_RE.pattern}",
                    key,
                )
            other = found.get(path.name)
            if other is not None and other != path:
                raise t.error(
                    f"duplicate task id {path.name!r}: {_rel(other, root)} and {_rel(path, root)}",
                    key,
                )
            found[path.name] = path
    if not found:
        raise t.error(f"no task directories matched {list(patterns)}", "tasks")

    ids = sorted(found)
    if excludes:
        ids = [i for i in ids if not any(fnmatch.fnmatchcase(i, p) for p in excludes)]
        if not ids:
            raise t.error(f"every task is excluded by {list(excludes)}", "exclude_tasks")
    if select is not None:
        ids = [i for i in ids if any(fnmatch.fnmatchcase(i, p) for p in select)]
        if not ids:
            raise ConfigError(f"no tasks match the selection {list(select)}", t.file)
    return [(i, found[i]) for i in ids]


# --------------------------------------------------------------------------- arms


def _agent_fields(t: _Table) -> dict[str, Any]:
    """Parse an ``[agent]`` / ``[arms.agent]`` table into only the keys it sets."""
    t.reject_unknown(_AGENT_KEYS)
    out: dict[str, Any] = {}
    if "adapter" in t.data:
        out["adapter"] = t.string("adapter", nonempty=True)
    for key in ("model", "effort"):
        if key in t.data:
            # An empty string clears an inherited default (adapter decides).
            out[key] = t.string(key) or None
    if "args" in t.data:
        out["args"] = t.strings("args")
    if "env" in t.data:
        env_t = t.table("env")
        assert env_t is not None
        env: dict[str, str] = {}
        for name, value in env_t.data.items():
            if not name or "=" in name or "\0" in name:
                raise env_t.error(f"invalid environment variable name {name!r}", name)
            if not isinstance(value, str):
                raise env_t.wrong_type(name, "a string", value)
            env[name] = value
        out["env"] = env
    if "command" in t.data:
        argv = t.strings("command")
        for i, item in enumerate(argv):
            _check_template(item, COMMAND_PLACEHOLDERS, t.where(f"command[{i}]"))
        # `command = []` means "not set", matching the documented default.
        out["command"] = argv or None
    if "options" in t.data:
        opt_t = t.table("options")
        assert opt_t is not None
        for name, value in opt_t.data.items():
            _check_values(value, opt_t, name)
        out["options"] = copy.deepcopy(opt_t.data)
    return out


def _merge_agent(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in over.items():
        if key == "args":
            merged["args"] = tuple(base.get("args", ())) + tuple(value)
        elif key in ("env", "options"):
            merged[key] = {**base.get(key, {}), **value}
        else:
            merged[key] = value
    return merged


def _load_arm(t: _Table, root: Path, defaults: dict[str, Any], defaults_where: str) -> Arm:
    t.reject_unknown(_ARM_KEYS)
    name = t.string("name", required=True)
    if not ID_RE.match(name):
        raise t.error(f"invalid arm name {name!r}: must match {ID_RE.pattern}", "name")

    overlay: Path | None = None
    if "overlay" in t.data:
        rel = _safe_relpath(t.string("overlay", nonempty=True), t, "overlay")
        overlay = (root / rel).resolve()
        if not overlay.is_dir():
            raise t.error(f"overlay directory not found: {rel}", "overlay")
    remove = tuple(
        _safe_relpath(item, t, f"remove[{i}]") for i, item in enumerate(t.strings("remove"))
    )

    agent_t = t.table("agent")
    over = _agent_fields(agent_t) if agent_t is not None else {}
    merged = _merge_agent(defaults, over)
    adapter_where = t.where("agent.adapter") if "adapter" in over else defaults_where
    if not merged.get("adapter"):
        raise t.error(
            "no adapter set: add 'adapter' to [agent] or to this arm's [arms.agent]",
            "agent.adapter",
        )
    spec = AgentSpec(
        adapter=merged["adapter"],
        model=merged.get("model"),
        effort=merged.get("effort"),
        args=tuple(merged.get("args", ())),
        env=dict(merged.get("env", {})),
        command=merged.get("command"),
        options=copy.deepcopy(merged.get("options", {})),
    )
    try:
        adapter = get_adapter(spec.adapter)
    except ConfigError as e:
        raise ConfigError(str(e), adapter_where) from None
    except ImportError as e:
        message = f"adapter {spec.adapter!r} could not be loaded: {e}"
        raise ConfigError(message, adapter_where) from e
    problems = adapter.validate(spec)
    if problems:
        raise t.error("; ".join(problems), "agent")

    return Arm(
        name=name,
        agent=spec,
        description=t.string("description", ""),
        overlay=overlay,
        remove=remove,
        prompt_prefix=t.string("prompt_prefix", ""),
        prompt_suffix=t.string("prompt_suffix", ""),
    )


# --------------------------------------------------------------------------- experiment


def load_experiment(
    path: str | Path,
    *,
    select_arms: Sequence[str] | None = None,
    select_tasks: Sequence[str] | None = None,
) -> Experiment:
    """Load, validate and fingerprint an experiment file.

    ``select_arms`` keeps only the named arms (config order is preserved; the baseline must be
    among them). ``select_tasks`` keeps tasks whose id matches any of the fnmatch patterns.
    """
    config_path = Path(path).expanduser().resolve()
    root = config_path.parent
    file = config_path.name
    t = _Table(_read_toml(config_path, file), file)
    t.reject_unknown(_EXPERIMENT_KEYS)

    name = t.string("name", required=True)
    if not ID_RE.match(name):
        raise t.error(f"invalid experiment name {name!r}: must match {ID_RE.pattern}", "name")
    description = t.string("description", "")
    scalars = {
        "repeats": t.integer("repeats", 1, minimum=1),
        "jobs": t.integer("jobs", 1, minimum=1),
        "seed": t.integer("seed", 0),
        "budget_usd": t.number("budget_usd", None),
        "timeout_s": t.number("timeout_s", 1800.0),
        "check_timeout_s": t.number("check_timeout_s", 600.0),
        "max_retries": t.integer("max_retries", 2, minimum=0),
        "timeout_is_failure": t.boolean("timeout_is_failure", True),
        "keep_workspaces": t.boolean("keep_workspaces", False),
    }
    workspace_root: Path | None = None
    ws = t.string("workspace_root", "")
    if ws:
        workspace_root = (root / Path(ws).expanduser()).resolve()

    agent_t = t.table("agent")
    defaults = _agent_fields(agent_t) if agent_t is not None else {}

    raw_arms = t.raw("arms", required=True)
    if not isinstance(raw_arms, list):
        raise t.wrong_type("arms", "an array of tables ([[arms]])", raw_arms)
    if not raw_arms:
        raise t.error("at least one arm is required", "arms")
    arms: list[Arm] = []
    seen: dict[str, int] = {}
    for i, raw in enumerate(raw_arms):
        key = f"arms[{i}]"
        if not isinstance(raw, dict):
            raise t.wrong_type(key, "a table", raw)
        arm = _load_arm(t.child(raw, key), root, defaults, t.where("agent.adapter"))
        if arm.name in seen:
            raise t.error(f"duplicate arm name {arm.name!r} (also arms[{seen[arm.name]}])",
                          f"{key}.name")
        seen[arm.name] = i
        arms.append(arm)

    all_names = [a.name for a in arms]
    if select_arms is not None:
        wanted = set(select_arms)
        unknown = sorted(wanted - set(all_names))
        if unknown:
            raise ConfigError(
                f"unknown arm(s) {', '.join(unknown)} (available: {', '.join(all_names)})", file
            )
        arms = [a for a in arms if a.name in wanted]
        if not arms:
            raise ConfigError("no arms selected", file)

    baseline = t.string("baseline", None, nonempty=True)
    if baseline is None:
        baseline = arms[0].name
    elif baseline not in all_names:
        raise t.error(
            f"baseline {baseline!r} is not an arm (arms: {', '.join(all_names)})", "baseline"
        )
    elif baseline not in {a.name for a in arms}:
        raise t.error(f"baseline {baseline!r} is excluded by the arm selection", "baseline")

    tasks = tuple(
        _load_task(task_dir, f"{_rel(task_dir, root)}/task.toml")
        for _, task_dir in _discover_tasks(t, root, select_tasks)
    )

    extra: dict[str, Any] = {}
    # Forward compatible: store the description once the model grows a field for it.
    if "description" in {f.name for f in fields(Experiment)}:
        extra["description"] = description
    exp = Experiment(
        name=name,
        config_path=config_path,
        root=root,
        tasks=tasks,
        arms=tuple(arms),
        baseline=baseline,
        workspace_root=workspace_root,
        **scalars,
        **extra,
    )
    return replace(exp, fingerprint=compute_fingerprint(exp))


# --------------------------------------------------------------------------- serialisation


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _command_json(cmd: Command | None) -> str | list[str] | None:
    if cmd is None or isinstance(cmd, str):
        return cmd
    return list(cmd)


def experiment_to_dict(exp: Experiment) -> dict:
    """JSON-safe view of the resolved experiment (paths relative to ``exp.root`` when inside it)."""
    root = exp.root

    def rel(p: Path | None) -> str | None:
        return None if p is None else _rel(p, root)

    return {
        "name": exp.name,
        "description": getattr(exp, "description", ""),
        "config": rel(exp.config_path),
        "repeats": exp.repeats,
        "jobs": exp.jobs,
        "seed": exp.seed,
        "budget_usd": exp.budget_usd,
        "timeout_s": exp.timeout_s,
        "check_timeout_s": exp.check_timeout_s,
        "max_retries": exp.max_retries,
        "timeout_is_failure": exp.timeout_is_failure,
        "keep_workspaces": exp.keep_workspaces,
        "workspace_root": rel(exp.workspace_root),
        "baseline": exp.baseline,
        "fingerprint": exp.fingerprint,
        "arms": [
            {
                "name": a.name,
                "description": a.description,
                "prompt_prefix": a.prompt_prefix,
                "prompt_suffix": a.prompt_suffix,
                "overlay": rel(a.overlay),
                "remove": list(a.remove),
                "agent": {
                    "adapter": a.agent.adapter,
                    "model": a.agent.model,
                    "effort": a.agent.effort,
                    "args": list(a.agent.args),
                    "env": dict(a.agent.env),
                    "command": _command_json(a.agent.command),
                    "options": _jsonable(a.agent.options),
                },
            }
            for a in exp.arms
        ],
        "tasks": [
            {
                "id": t.id,
                "path": rel(t.path),
                "prompt": t.prompt,
                "check": _command_json(t.check),
                "setup": _command_json(t.setup),
                "repo": rel(t.repo),
                "checks": rel(t.checks),
                "solution": rel(t.solution),
                "timeout_s": t.timeout_s,
                "check_timeout_s": t.check_timeout_s,
                "tags": list(t.tags),
            }
            for t in exp.tasks
        ],
    }


# --------------------------------------------------------------------------- fingerprint


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        # Dangling symlinks and the like still contribute, just not their (absent) bytes.
        return "unreadable"
    return h.hexdigest()


def _tree_digest(base: Path) -> list[list[str]]:
    entries: list[list[str]] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _IGNORED_NAMES]
        for name in filenames:
            if name in _IGNORED_NAMES or name.endswith(_IGNORED_SUFFIXES):
                continue
            path = Path(dirpath) / name
            entries.append([path.relative_to(base).as_posix(), _file_sha256(path)])
    entries.sort()
    return entries


def compute_fingerprint(exp: Experiment) -> str:
    """sha256 identifying everything that affects results: config plus task/overlay file bytes.

    Settings that may change between sessions of one run (jobs, budget, workspace handling,
    descriptions) are excluded, so a resumed run can adjust them.
    """
    data = experiment_to_dict(exp)
    for key in _VOLATILE_KEYS:
        data.pop(key, None)
    for arm in data["arms"]:
        arm.pop("description", None)
    data["files"] = {
        "tasks": {t.id: _tree_digest(t.path) for t in exp.tasks},
        "overlays": {a.name: _tree_digest(a.overlay) for a in exp.arms if a.overlay is not None},
    }
    blob = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)
    return hashlib.sha256(blob.encode("ascii")).hexdigest()
