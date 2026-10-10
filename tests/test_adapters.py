"""Tests for the agent adapters: argv construction, option validation and output parsing."""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_ab.adapters import ADAPTER_NAMES, base, get_adapter
from agent_ab.adapters import command as command_mod
from agent_ab.adapters.claude_code import (
    SYSTEM_PROMPT_FILE,
    ClaudeCodeAdapter,
    parse_result_text,
)
from agent_ab.adapters.codex import CodexAdapter, parse_events
from agent_ab.adapters.command import CommandAdapter, _expand, _read_usage_file
from agent_ab.adapters.mock import MockAdapter
from agent_ab.errors import AdapterError, ConfigError
from agent_ab.model import AgentSpec, Arm, ProcResult, Task, TrialContext

FIXTURES = Path(__file__).parent / "fixtures" / "adapters"


def make_ctx(tmp_path: Path, spec: AgentSpec, *, prompt: str = "Fix it.", solution=None):
    ws = tmp_path / "ws"
    art = tmp_path / "art"
    ws.mkdir(exist_ok=True)
    art.mkdir(exist_ok=True)
    task = Task(id="t1", path=tmp_path, prompt=prompt, check=("x",), solution=solution)
    return TrialContext(
        spec=spec,
        task=task,
        arm=Arm(name="a", agent=spec),
        repeat=0,
        attempt=0,
        prompt=prompt,
        workspace=ws,
        artifacts=art,
        seed=42,
    )


def proc_result(tmp_path: Path, stdout: str | bytes = "", stderr: str = "", code=0, **kw):
    out, err = tmp_path / "agent.stdout", tmp_path / "agent.stderr"
    if isinstance(stdout, bytes):
        out.write_bytes(stdout)
    else:
        out.write_text(stdout, encoding="utf-8")
    err.write_text(stderr, encoding="utf-8")
    return ProcResult(
        exit_code=code,
        timed_out=kw.get("timed_out", False),
        duration_s=1.0,
        stdout_path=out,
        stderr_path=err,
        start_error=kw.get("start_error"),
    )


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- registry


def test_registry_classes():
    expected = {
        "claude-code": ClaudeCodeAdapter,
        "codex": CodexAdapter,
        "command": CommandAdapter,
        "mock": MockAdapter,
    }
    for name in ADAPTER_NAMES:
        adapter = get_adapter(name)
        assert isinstance(adapter, expected[name])
        assert adapter.name == name


# --------------------------------------------------------------------------- claude-code

CLAUDE_BASE = ["-p", "--output-format", "json", "--no-session-persistence"]


def claude_argv(tmp_path, **kw):
    options = kw.pop("options", {"executable": "definitely-not-a-real-claude"})
    spec = AgentSpec(adapter="claude-code", options=options, **kw)
    assert ClaudeCodeAdapter().validate(spec) == []
    inv = ClaudeCodeAdapter().build(make_ctx(tmp_path, spec, prompt="Do the thing"))
    assert inv.stdin == "Do the thing"
    assert inv.cwd == tmp_path / "ws"
    return inv.argv


def test_claude_minimal_argv(tmp_path):
    argv = claude_argv(tmp_path)
    assert argv == [
        "definitely-not-a-real-claude",
        *CLAUDE_BASE,
        "--permission-mode",
        "bypassPermissions",
    ]


def test_claude_all_options_argv(tmp_path):
    argv = claude_argv(
        tmp_path,
        model="opus",
        effort="xhigh",
        args=("--verbose",),
        env={"A": "1"},
        options={
            "executable": "nope-claude",
            "permission_mode": "acceptEdits",
            "max_budget_usd": 2.5,
            "max_turns": 30,
            "safe_mode": True,
            "bare": True,
            "setting_sources": "project,local",
            "append_system_prompt": "Be brief.",
        },
    )
    assert argv == [
        "nope-claude",
        *CLAUDE_BASE,
        "--permission-mode",
        "acceptEdits",
        "--model",
        "opus",
        "--effort",
        "xhigh",
        "--max-budget-usd",
        "2.5",
        "--max-turns",
        "30",
        "--safe-mode",
        "--bare",
        "--setting-sources",
        "project,local",
        "--append-system-prompt-file",
        str(tmp_path / "art" / SYSTEM_PROMPT_FILE),
        "--verbose",
    ]
    assert (tmp_path / "art" / SYSTEM_PROMPT_FILE).read_text(encoding="utf-8") == "Be brief."


FLAG_OPTIONS = {
    "max_budget_usd": (1, ["--max-budget-usd", "1"]),
    "max_turns": (5, ["--max-turns", "5"]),
    "safe_mode": (True, ["--safe-mode"]),
    "bare": (True, ["--bare"]),
    "setting_sources": ("", ["--setting-sources", ""]),
    "append_system_prompt": ("x y", ["--append-system-prompt-file", SYSTEM_PROMPT_FILE]),
}


@pytest.mark.parametrize("r", range(len(FLAG_OPTIONS) + 1))
def test_claude_option_combinations(tmp_path, r):
    for combo in itertools.combinations(FLAG_OPTIONS, r):
        options = {"executable": "nope-claude", **{k: FLAG_OPTIONS[k][0] for k in combo}}
        argv = claude_argv(tmp_path, options=options)
        expected = ["nope-claude", *CLAUDE_BASE, "--permission-mode", "bypassPermissions"]
        for k in FLAG_OPTIONS:  # flags are emitted in a fixed order
            if k in combo:
                expected += [
                    str(tmp_path / "art" / x) if x == SYSTEM_PROMPT_FILE else x
                    for x in FLAG_OPTIONS[k][1]
                ]
        assert argv == expected


def test_claude_false_flags_omitted(tmp_path):
    argv = claude_argv(
        tmp_path, options={"executable": "x-claude", "safe_mode": False, "bare": False}
    )
    assert "--safe-mode" not in argv and "--bare" not in argv


def test_claude_resolves_executable(tmp_path):
    spec = AgentSpec(adapter="claude-code", options={"executable": sys.executable})
    argv = ClaudeCodeAdapter().build(make_ctx(tmp_path, spec)).argv
    assert Path(argv[0]).resolve() == Path(sys.executable).resolve()
    assert ClaudeCodeAdapter().check_available(spec) is None
    missing = AgentSpec(adapter="claude-code", options={"executable": "no-such-claude-xyz"})
    assert "not found" in ClaudeCodeAdapter().check_available(missing)


@pytest.mark.parametrize(
    "kw, fragment",
    [
        ({"effort": "extreme"}, "effort"),
        ({"options": {"permission_mode": "yolo"}}, "permission_mode"),
        ({"options": {"max_budget_usd": 0}}, "max_budget_usd"),
        ({"options": {"max_budget_usd": "5"}}, "max_budget_usd"),
        ({"options": {"max_turns": 2.5}}, "max_turns"),
        ({"options": {"max_turns": True}}, "max_turns"),
        ({"options": {"safe_mode": "yes"}}, "safe_mode"),
        ({"options": {"bare": 1}}, "bare"),
        ({"options": {"setting_sources": "user,global"}}, "setting_sources"),
        ({"options": {"setting_sources": ["user"]}}, "setting_sources"),
        ({"options": {"append_system_prompt": 3}}, "append_system_prompt"),
        ({"options": {"executable": ""}}, "executable"),
        ({"options": {"sandbox": "x"}}, "unknown option"),
    ],
)
def test_claude_validate_errors(kw, fragment):
    problems = ClaudeCodeAdapter().validate(AgentSpec(adapter="claude-code", **kw))
    assert any(fragment in p for p in problems), problems


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_claude_valid_efforts(effort):
    assert ClaudeCodeAdapter().validate(AgentSpec(adapter="claude-code", effort=effort)) == []


def claude_parse(tmp_path, stdout, stderr="", code=0, **kw):
    spec = AgentSpec(adapter="claude-code")
    return ClaudeCodeAdapter().parse(
        make_ctx(tmp_path, spec), proc_result(tmp_path, stdout, stderr, code, **kw)
    )


def test_claude_parse_success(tmp_path):
    u = claude_parse(tmp_path, fixture("claude_success.json"))
    assert u.cost_usd == pytest.approx(0.18342)
    assert (u.input_tokens, u.output_tokens) == (23, 1873)
    assert (u.cache_read_tokens, u.cache_write_tokens) == (96410, 11024)
    assert u.turns == 7
    assert u.final_message.startswith("Fixed `slugify()`")
    assert u.infra_error is None


def test_claude_parse_noisy_prefers_result(tmp_path):
    u = claude_parse(tmp_path, fixture("claude_noisy.txt"))
    assert u.turns == 3 and u.cost_usd == pytest.approx(0.042) and u.final_message == "Done."


def test_claude_parse_pretty_printed(tmp_path):
    u = claude_parse(tmp_path, "log line\n" + fixture("claude_pretty.json"))
    assert u.final_message == "ok" and u.output_tokens == 2


@pytest.mark.parametrize(
    "name, subtype",
    [
        ("claude_max_turns.json", "error_max_turns"),
        ("claude_max_budget.json", "error_max_budget_usd"),
    ],
)
def test_claude_limits_are_agent_failures(tmp_path, name, subtype):
    u = claude_parse(tmp_path, fixture(name), code=1)
    assert u.infra_error is None
    assert u.final_message == subtype
    assert u.cost_usd is not None and u.turns is not None


def test_claude_ordinary_error_is_agent_failure(tmp_path):
    u = claude_parse(tmp_path, fixture("claude_agent_error.json"), code=1)
    assert u.infra_error is None
    assert u.final_message == "error_during_execution"


@pytest.mark.parametrize(
    "name, needle",
    [("claude_auth_error.json", "Invalid API key"), ("claude_rate_limited.json", "429")],
)
def test_claude_infra_errors_in_result(tmp_path, name, needle):
    u = claude_parse(tmp_path, fixture(name), code=1)
    assert u.infra_error is not None and needle in u.infra_error
    assert len(u.infra_error) <= 500


def test_claude_success_mentioning_429_is_not_infra(tmp_path):
    obj = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "Fixed the off-by-one on line 429; rate limit logic untouched.",
    }
    assert claude_parse(tmp_path, json.dumps(obj)).infra_error is None


def test_claude_garbage_nonzero_exit_is_infra(tmp_path):
    stderr = "x" * 2000 + "Error: connect ECONNRESET 1.2.3.4:443"
    u = claude_parse(tmp_path, (FIXTURES / "claude_garbage.txt").read_bytes(), stderr, code=1)
    assert u.infra_error is not None
    assert "code 1" in u.infra_error and "ECONNRESET" in u.infra_error
    assert len(u.infra_error) < 600


def test_claude_garbage_exit_zero_never_raises(tmp_path):
    u = claude_parse(tmp_path, (FIXTURES / "claude_garbage.txt").read_bytes())
    assert u.infra_error is None and u.cost_usd is None


def test_claude_stderr_auth_without_json(tmp_path):
    u = claude_parse(tmp_path, "", "Error: Authentication failed (401)", code=1)
    assert "Authentication failed" in u.infra_error


def test_claude_timeout_and_start_error(tmp_path):
    assert claude_parse(tmp_path, "", "", code=None, timed_out=True).infra_error is None
    u = claude_parse(tmp_path, "", "", code=None, start_error="WinError 2")
    assert "WinError 2" in u.infra_error


def test_claude_parse_real_success(tmp_path):
    # Captured from claude 2.1.287 (haiku, effort low); ids replaced.
    u = claude_parse(tmp_path, fixture("claude_real_success.json"))
    assert u.cost_usd == pytest.approx(0.0224563)
    assert (u.input_tokens, u.output_tokens) == (9, 55)
    assert (u.cache_read_tokens, u.cache_write_tokens) == (26523, 9760)
    assert u.turns == 1 and u.final_message == "OK" and u.infra_error is None


def test_claude_real_unknown_model_is_infra(tmp_path):
    # Real output for an unknown --model: is_error with api_error_status 404, zero cost.
    u = claude_parse(tmp_path, fixture("claude_real_unknown_model.json"), code=1)
    assert u.infra_error is not None and u.infra_error.startswith("API error 404")
    assert "selected model" in u.infra_error


@pytest.mark.parametrize(
    "status, infra",
    [(400, False), (401, True), (404, True), (429, True), (529, True), (None, False)],
)
def test_claude_api_error_status(status, infra):
    obj = {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "result": "something went wrong",
        "api_error_status": status,
    }
    assert (parse_result_text(json.dumps(obj), "", 1).infra_error is not None) is infra


def test_claude_parse_wrong_types_ignored():
    obj = {
        "type": "result",
        "total_cost_usd": "1.0",
        "num_turns": True,
        "usage": {"input_tokens": "12", "output_tokens": -1},
        "result": 5,
    }
    u = parse_result_text(json.dumps(obj), "", 0)
    assert (u.cost_usd, u.turns, u.input_tokens, u.output_tokens, u.final_message) == (
        None,
        None,
        None,
        None,
        None,
    )


def test_claude_last_object_fallback():
    u = parse_result_text('{"a": 1}\n{"num_turns": 4}\n', "", 0)
    assert u.turns == 4


# --------------------------------------------------------------------------- codex


def codex_build(tmp_path, **kw):
    options = kw.pop("options", {})
    options.setdefault("executable", "nope-codex")
    spec = AgentSpec(adapter="codex", options=options, **kw)
    assert CodexAdapter().validate(spec) == []
    inv = CodexAdapter().build(make_ctx(tmp_path, spec, prompt="P"))
    assert inv.stdin == "P"
    return inv.argv


def test_codex_minimal_argv(tmp_path):
    ws = str(tmp_path / "ws")
    assert codex_build(tmp_path) == [
        "nope-codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--ephemeral",
        "-C",
        ws,
        "--sandbox",
        "workspace-write",
        "-",
    ]


@pytest.mark.parametrize(
    "bypass, sandbox, model, effort, ignore, args",
    [
        c
        for c in itertools.product(
            [False, True],
            [None, "read-only"],
            [None, "gpt-5"],
            [None, "high"],
            [False, True],
            [(), ("--oss",)],
        )
        if not (c[0] and c[1])
    ],
)  # bypass + sandbox: see validate test
def test_codex_argv_combinations(tmp_path, bypass, sandbox, model, effort, ignore, args):
    options = {"bypass_sandbox": bypass, "ignore_user_config": ignore}
    if sandbox:
        options["sandbox"] = sandbox
    argv = codex_build(tmp_path, model=model, effort=effort, args=args, options=options)
    expected = [
        "nope-codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--ephemeral",
        "-C",
        str(tmp_path / "ws"),
    ]
    if bypass:
        expected.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        expected += ["--sandbox", sandbox or "workspace-write"]
    if model:
        expected += ["-m", model]
    if effort:
        expected += ["-c", f"model_reasoning_effort={effort}"]
    if ignore:
        expected.append("--ignore-user-config")
    expected += [*args, "-"]
    assert argv == expected


@pytest.mark.parametrize(
    "kw, fragment",
    [
        ({"effort": "bogus"}, "effort"),
        ({"options": {"sandbox": "full"}}, "sandbox"),
        ({"options": {"bypass_sandbox": True, "sandbox": "read-only"}}, "mutually exclusive"),
        ({"options": {"ignore_user_config": "true"}}, "ignore_user_config"),
        ({"options": {"price_input_per_mtok": -1}}, "price_input_per_mtok"),
        ({"options": {"price_output_per_mtok": "2"}}, "price_output_per_mtok"),
        ({"options": {"permission_mode": "plan"}}, "unknown option"),
    ],
)
def test_codex_validate_errors(kw, fragment):
    problems = CodexAdapter().validate(AgentSpec(adapter="codex", **kw))
    assert any(fragment in p for p in problems), problems


PRICES = {
    "price_input_per_mtok": 1.25,
    "price_cached_input_per_mtok": 0.125,
    "price_output_per_mtok": 10.0,
}


def test_codex_parse_success_with_cost():
    u = parse_events(fixture("codex_success.jsonl"), "", 0, PRICES)
    assert u.turns == 1
    assert u.final_message == "Fixed slugify to collapse separators."
    assert (u.input_tokens, u.cache_read_tokens, u.output_tokens) == (315, 24448, 122)
    expected = (315 * 1.25 + 24448 * 0.125 + 122 * 10.0) / 1e6
    assert u.cost_usd == pytest.approx(expected)
    assert u.infra_error is None


def test_codex_cost_needs_prices():
    assert parse_events(fixture("codex_success.jsonl"), "", 0, {}).cost_usd is None
    partial = {k: v for k, v in PRICES.items() if k != "price_cached_input_per_mtok"}
    # Cached tokens present but no cached price: refuse to guess.
    assert parse_events(fixture("codex_success.jsonl"), "", 0, partial).cost_usd is None


def test_codex_multi_turn_and_malformed_lines():
    u = parse_events(fixture("codex_multi_turn.jsonl"), "", 0, PRICES)
    assert u.turns == 2
    assert (u.input_tokens, u.cache_read_tokens, u.output_tokens) == (2000, 2000, 400)
    assert u.final_message == "second"


def test_codex_turn_failed_rate_limit_is_infra():
    u = parse_events(fixture("codex_turn_failed.jsonl"), "", 1, {})
    assert u.infra_error is not None and "429" in u.infra_error
    assert u.turns == 0


def test_codex_turn_failed_other_is_agent_failure():
    u = parse_events(fixture("codex_agent_failed.jsonl"), "", 1, {})
    assert u.infra_error is None
    assert u.final_message == "model produced an invalid tool call"


def test_codex_recovered_error_is_not_infra():
    u = parse_events(fixture("codex_recovered.jsonl"), "", 0, PRICES)
    assert u.infra_error is None and u.final_message == "done" and u.turns == 1


def test_codex_parse_real_success():
    # Captured from codex-cli 0.162.0; adds cache_write_input_tokens and reasoning_output_tokens.
    u = parse_events(fixture("codex_real_success.jsonl"), "", 0, PRICES)
    assert u.turns == 1 and u.final_message == "OK" and u.infra_error is None
    assert (u.input_tokens, u.cache_read_tokens, u.output_tokens) == (4766, 9984, 5)
    assert u.cache_write_tokens == 0


def test_codex_real_unsupported_model_is_infra():
    # The leading "Model metadata ... not found" item is only a warning and is ignored.
    u = parse_events(fixture("codex_real_unsupported_model.jsonl"), "", 1, {})
    assert u.infra_error is not None and "not supported" in u.infra_error
    assert u.turns == 0


def test_codex_real_sandbox_failure_is_infra():
    # Every command was rejected by the Windows sandbox; the turn itself "completed".
    stderr = fixture("codex_real_sandbox_failed.stderr")
    u = parse_events(fixture("codex_real_sandbox_failed.jsonl"), stderr, 0, {})
    assert u.infra_error is not None and "setup refresh had errors" in u.infra_error
    assert u.infra_error.startswith("codex sandbox could not run commands")
    assert u.turns == 1 and u.output_tokens == 1183


def test_codex_sandbox_noise_after_working_commands_is_not_infra():
    events = fixture("codex_success.jsonl").replace('"exit_code":null', '"exit_code":0')
    stderr = fixture("codex_real_sandbox_failed.stderr")
    assert parse_events(events, stderr, 0, {}).infra_error is None


@pytest.mark.parametrize("effort", ["low", "max", "ultra"])
def test_codex_valid_efforts(effort):
    assert CodexAdapter().validate(AgentSpec(adapter="codex", effort=effort)) == []


def test_codex_no_events_nonzero_exit_is_infra(tmp_path):
    spec = AgentSpec(adapter="codex")
    res = proc_result(
        tmp_path,
        (FIXTURES / "claude_garbage.txt").read_bytes(),
        "Error: unexpected argument",
        code=2,
    )
    u = CodexAdapter().parse(make_ctx(tmp_path, spec), res)
    assert "code 2" in u.infra_error and "unexpected argument" in u.infra_error


def test_codex_empty_output_exit_zero():
    u = parse_events("", "", 0, {})
    assert u.infra_error is None and u.turns is None and u.cost_usd is None


# --------------------------------------------------------------------------- command


def test_expand_placeholders():
    vals = {"a": "1", "b": "two"}
    assert _expand("x{a}-{b}", vals) == "x1-two"
    assert _expand("{{a}} {{{a}}}", vals) == "{a} {1}"
    with pytest.raises(ConfigError, match="unknown placeholder"):
        _expand("{nope}", vals)
    with pytest.raises(ConfigError, match="unbalanced"):
        _expand("{a", vals)


def test_command_build_expands_and_writes_prompt(tmp_path):
    spec = AgentSpec(
        adapter="command",
        model="m1",
        effort="e1",
        command=(
            "{python}",
            "-c",
            "pass",
            "{prompt_file}",
            "{prompt}",
            "{workspace}",
            "{artifacts}",
            "{model}",
            "{effort}",
            "{seed}",
            "{{lit}}",
        ),
    )
    assert CommandAdapter().validate(spec) == []
    ctx = make_ctx(tmp_path, spec, prompt="hello\nworld")
    inv = CommandAdapter().build(ctx)
    prompt_file = ctx.artifacts / "prompt.md"
    assert prompt_file.read_bytes() == b"hello\nworld\n"
    assert Path(inv.argv[0]).resolve() == Path(sys.executable).resolve()
    assert inv.argv[1:] == [
        "-c",
        "pass",
        str(prompt_file),
        "hello\nworld",
        str(ctx.workspace),
        str(ctx.artifacts),
        "m1",
        "e1",
        "42",
        "{lit}",
    ]
    assert inv.stdin is None


def test_command_stdin_option(tmp_path):
    spec = AgentSpec(adapter="command", command=("tool",), options={"stdin": True})
    assert CommandAdapter().build(make_ctx(tmp_path, spec, prompt="p")).stdin == "p"


def test_command_shell_option_runs(tmp_path):
    spec = AgentSpec(
        adapter="command",
        options={"shell": True},
        command=("{python}", "-c", '"print(1+1)"', ">", "{artifacts}/out.txt"),
    )
    inv = CommandAdapter().build(make_ctx(tmp_path, spec))
    assert inv.argv[0] != "{python}"
    subprocess.run(inv.argv, cwd=inv.cwd, check=True, timeout=30)
    assert (tmp_path / "art" / "out.txt").read_text().strip() == "2"


@pytest.mark.parametrize(
    "kw, fragment",
    [
        ({}, "requires a non-empty"),
        ({"command": ()}, "requires a non-empty"),
        ({"command": ("x", "{bogus}")}, "unknown placeholder"),
        ({"command": ("x", "{")}, "unbalanced"),
        ({"command": ("x",), "options": {"stdin": "yes"}}, "stdin"),
        ({"command": ("x",), "options": {"shell": 1}}, "shell"),
        ({"command": ("x",), "options": {"timeout": 1}}, "unknown option"),
    ],
)
def test_command_validate_errors(kw, fragment):
    problems = CommandAdapter().validate(AgentSpec(adapter="command", **kw))
    assert any(fragment in p for p in problems), problems


def test_command_check_available():
    a = CommandAdapter()
    assert a.check_available(AgentSpec(adapter="command", command=("{python}",))) is None
    assert a.check_available(AgentSpec(adapter="command", command=(sys.executable,))) is None
    assert "not found" in a.check_available(AgentSpec(adapter="command", command=("nope-xyz",)))


def test_usage_json_contract(tmp_path):
    path = tmp_path / "usage.json"
    path.write_text(
        json.dumps(
            {
                "cost_usd": 0.5,
                "input_tokens": 10,
                "output_tokens": "20",
                "cache_read_tokens": 1.5,
                "cache_write_tokens": True,
                "turns": 3,
                "final_message": "hi",
                "infra_error": 7,
                "extra": "ignored",
            }
        ),
        encoding="utf-8",
    )
    u = _read_usage_file(path)
    assert (u.cost_usd, u.input_tokens, u.turns, u.final_message) == (0.5, 10, 3, "hi")
    assert u.output_tokens is None and u.cache_read_tokens is None
    assert u.cache_write_tokens is None and u.infra_error is None


@pytest.mark.parametrize(
    "content", ["", "not json", "[1, 2]", '{"cost_usd": "NaN"}', '{"cost_usd": -1}']
)
def test_usage_json_garbage(tmp_path, content):
    path = tmp_path / "usage.json"
    path.write_text(content, encoding="utf-8")
    u = _read_usage_file(path)
    assert u.cost_usd is None and u.infra_error is None


def test_command_parse(tmp_path):
    spec = AgentSpec(adapter="command", command=("x",))
    ctx = make_ctx(tmp_path, spec)
    res = proc_result(tmp_path, code=5)
    assert CommandAdapter().parse(ctx, res).infra_error is None  # non-zero exit is not infra
    (ctx.artifacts / "usage.json").write_text('{"infra_error": "quota"}', encoding="utf-8")
    assert CommandAdapter().parse(ctx, res).infra_error == "quota"


def test_command_end_to_end(tmp_path):
    script = (
        "import json,pathlib,sys; a=pathlib.Path(sys.argv[1]);"
        "p=(a/'prompt.md').read_text(encoding='utf-8');"
        "(a/'usage.json').write_text(json.dumps(dict(cost_usd=0.25,final_message=p)))"
    )
    spec = AgentSpec(adapter="command", command=("{python}", "-c", script, "{artifacts}"))
    ctx = make_ctx(tmp_path, spec, prompt="say hi")
    inv = CommandAdapter().build(ctx)
    cp = subprocess.run(inv.argv, cwd=inv.cwd, timeout=30)
    u = CommandAdapter().parse(ctx, proc_result(tmp_path, code=cp.returncode))
    assert (u.cost_usd, u.final_message) == (0.25, "say hi\n")


# --------------------------------------------------------------------------- mock


@pytest.mark.parametrize(
    "options, fragment",
    [
        ({"solve_rate": 1.5}, "solve_rate"),
        ({"crash_rate": -0.1}, "crash_rate"),
        ({"infra_error_rate": "0"}, "infra_error_rate"),
        ({"cost_usd": [0.5, 0.1]}, "cost_usd"),
        ({"cost_usd": [0.1]}, "cost_usd"),
        ({"duration_s": -1}, "duration_s"),
        ({"tokens": 1.5}, "tokens"),
        ({"fail_mode": "explode"}, "fail_mode"),
        ({"task_rates": {"t1": 2}}, "task_rates"),
        ({"task_rates": [0.5]}, "task_rates"),
        ({"bogus": 1}, "unknown option"),
    ],
)
def test_mock_validate_errors(options, fragment):
    problems = MockAdapter().validate(AgentSpec(adapter="mock", options=options))
    assert any(fragment in p for p in problems), problems


def test_mock_validate_ok():
    spec = AgentSpec(
        adapter="mock",
        options={
            "solve_rate": 0.3,
            "cost_usd": [0.01, 0.05],
            "duration_s": 0,
            "tokens": 500,
            "fail_mode": "break",
            "task_rates": {"t1": 1.0},
            "crash_rate": 0.1,
            "infra_error_rate": 0.05,
        },
    )
    assert MockAdapter().validate(spec) == []


def test_mock_adapter_end_to_end(tmp_path):
    solution = tmp_path / "solution"
    solution.mkdir()
    (solution / "fixed.py").write_text("VALUE = 1\n", encoding="utf-8")
    spec = AgentSpec(adapter="mock", options={"solve_rate": 1.0, "cost_usd": 0.02})
    ctx = make_ctx(tmp_path, spec, solution=solution)
    inv = MockAdapter().build(ctx)
    assert inv.argv[:3] == [sys.executable, "-m", "agent_ab.mock_agent"]
    env = {**os.environ, **inv.env}
    cp = subprocess.run(inv.argv, cwd=inv.cwd, env=env, timeout=60, capture_output=True)
    assert cp.returncode == 0, cp.stderr
    assert (ctx.workspace / "fixed.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    u = MockAdapter().parse(ctx, proc_result(tmp_path, code=0))
    assert u.cost_usd == pytest.approx(0.02) and u.infra_error is None and u.input_tokens


def test_mock_check_available():
    assert MockAdapter().check_available(AgentSpec(adapter="mock")) is None


def test_mock_rejects_args():
    problems = MockAdapter().validate(AgentSpec(adapter="mock", args=("--verbose",)))
    assert any("does not accept 'args'" in p for p in problems), problems
    assert MockAdapter().validate(AgentSpec(adapter="mock", args=())) == []


# --------------------------------------------------------------------------- command prompt file


def test_command_keeps_existing_identical_prompt_file(tmp_path):
    spec = AgentSpec(adapter="command", command=("tool", "{prompt_file}"))
    ctx = make_ctx(tmp_path, spec, prompt="same")
    path = ctx.artifacts / "prompt.md"
    path.write_bytes(b"same\n")  # what the runner writes
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    CommandAdapter().build(ctx)
    assert path.stat().st_mtime_ns == 1_000_000_000
    assert path.read_bytes() == b"same\n"


def test_command_rewrites_different_prompt_file(tmp_path):
    spec = AgentSpec(adapter="command", command=("tool", "{prompt_file}"))
    ctx = make_ctx(tmp_path, spec, prompt="new")
    (ctx.artifacts / "prompt.md").write_bytes(b"stale")
    CommandAdapter().build(ctx)
    assert (ctx.artifacts / "prompt.md").read_bytes() == b"new\n"


# --------------------------------------------------------------------------- command shell mode


@pytest.mark.parametrize("item", ["{prompt}", "--msg={prompt}", "x{prompt}y"])
def test_command_shell_rejects_prompt_placeholder(item):
    spec = AgentSpec(adapter="command", command=("tool", item), options={"shell": True})
    problems = CommandAdapter().validate(spec)
    assert any("{prompt} cannot be used with shell = true" in p for p in problems), problems
    assert any("{prompt_file}" in p for p in problems)


def test_command_shell_allows_prompt_file_and_literal_braces():
    for command in (("tool", "{prompt_file}"), ("tool", "{{prompt}}")):
        spec = AgentSpec(adapter="command", command=command, options={"shell": True})
        assert CommandAdapter().validate(spec) == []
    # Without shell mode {prompt} stays allowed.
    assert CommandAdapter().validate(AgentSpec(adapter="command", command=("t", "{prompt}"))) == []


def test_command_shell_rejects_newline_in_value(tmp_path):
    spec = AgentSpec(
        adapter="command", model="a\nb", command=("tool", "{model}"), options={"shell": True}
    )
    with pytest.raises(AdapterError, match="newline"):
        CommandAdapter().build(make_ctx(tmp_path, spec))
    # Unused placeholders are not checked.
    ok = AgentSpec(adapter="command", model="a\nb", command=("tool",), options={"shell": True})
    CommandAdapter().build(make_ctx(tmp_path, ok))


@pytest.mark.parametrize("value", ["100%", "%USERNAME%", "hi!", 'say "x"'])
def test_command_shell_rejects_cmd_expansion_on_windows(tmp_path, monkeypatch, value):
    monkeypatch.setattr(command_mod, "IS_WINDOWS", True)
    spec = AgentSpec(
        adapter="command", model=value, command=("tool", "{model}"), options={"shell": True}
    )
    with pytest.raises(AdapterError, match="cmd.exe"):
        CommandAdapter().build(make_ctx(tmp_path, spec))
    monkeypatch.setattr(command_mod, "IS_WINDOWS", False)
    CommandAdapter().build(make_ctx(tmp_path, spec))


def test_command_shell_keeps_metacharacters_literal(tmp_path):
    out = tmp_path / "out.txt"
    marker = tmp_path / "pwned.txt"
    value = f"a&b|c^d<e>f & echo x>{marker}"
    script = "import sys; open(sys.argv[1], 'w', encoding='utf-8').write(sys.argv[2])"
    spec = AgentSpec(
        adapter="command",
        model=value,
        options={"shell": True},
        command=("{python}", "-c", f'"{script}"', str(out), "{model}"),
    )
    inv = CommandAdapter().build(make_ctx(tmp_path, spec))
    subprocess.run(inv.argv, cwd=inv.cwd, check=True, timeout=30)
    assert out.read_text(encoding="utf-8") == value
    assert not marker.exists()


# --------------------------------------------------------------------------- Windows batch shims


@pytest.mark.parametrize("ch", list('&|<>^%!"\r\n'))
def test_batch_argv_problems_flags_each_character(ch):
    problems = base.batch_argv_problems(["C:/bin/claude.CMD", "-p", f"a{ch}b"])
    assert len(problems) == 1
    assert "batch file" in problems[0] and "native executable" in problems[0]


def test_batch_argv_problems_ignores_safe_and_non_batch():
    assert base.batch_argv_problems(["x.cmd", "-p", "C:/Program Files/a b", "k=v", "(x)"]) == []
    assert base.batch_argv_problems(["claude.exe", "a&b", "100%"]) == []
    assert base.batch_argv_problems(["claude", "a&b"]) == []
    assert base.batch_argv_problems([]) == []
    assert base.batch_argv_problems(["run.bat", "a&b"])
    # The executable path itself is not re-parsed as an argument.
    assert base.batch_argv_problems(["C:/odd&dir/run.cmd", "ok"]) == []


def test_check_batch_argv_only_on_windows(monkeypatch):
    monkeypatch.setattr(base, "IS_WINDOWS", True)
    with pytest.raises(AdapterError, match="batch file"):
        base.check_batch_argv(["claude.cmd", "%USERNAME%"])
    base.check_batch_argv(["claude.cmd", "plain"])
    monkeypatch.setattr(base, "IS_WINDOWS", False)
    base.check_batch_argv(["claude.cmd", "%USERNAME%"])
    assert base.batch_argv_issue(["claude.cmd", "%USERNAME%"]) is None


def fake_shim(tmp_path: Path, name: str) -> Path:
    """A ``.cmd`` that records its argv as JSON, like an npm shim forwarding ``%*``."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "dump.py").write_text(
        "import json, os, sys\n"
        "with open(os.path.join(os.path.dirname(__file__), 'argv.json'), 'w') as f:\n"
        "    json.dump(sys.argv[1:], f)\n"
        "sys.stdin.read()\n",
        encoding="utf-8",
    )
    shim = bindir / name
    shim.write_text(f'@"{sys.executable}" "%~dp0dump.py" %*\r\n', encoding="utf-8", newline="")
    shim.chmod(0o755)
    return shim


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(base, "IS_WINDOWS", True)
    monkeypatch.setattr(command_mod, "IS_WINDOWS", True)


def test_claude_batch_shim_checked_up_front(tmp_path, windows):
    shim = str(fake_shim(tmp_path, "claude.cmd"))
    a = ClaudeCodeAdapter()
    ok = AgentSpec(
        adapter="claude-code",
        model="sonnet",
        options={"executable": shim, "append_system_prompt": "a & b\n100%"},
    )
    assert a.check_available(ok) is None  # the system prompt goes through a file
    for spec in (
        AgentSpec(adapter="claude-code", model="x&y", options={"executable": shim}),
        AgentSpec(adapter="claude-code", args=("--foo=%PATH%",), options={"executable": shim}),
    ):
        msg = a.check_available(spec)
        assert msg and msg.startswith("claude-code:") and "batch file" in msg, msg


def test_claude_batch_shim_rejects_unsafe_artifacts_path(tmp_path, windows):
    shim = str(fake_shim(tmp_path, "claude.cmd"))
    spec = AgentSpec(
        adapter="claude-code", options={"executable": shim, "append_system_prompt": "hi"}
    )
    (tmp_path / "100%").mkdir()
    ctx = make_ctx(tmp_path / "100%", spec)
    with pytest.raises(AdapterError, match="batch file"):
        ClaudeCodeAdapter().build(ctx)


def test_codex_batch_shim_checked(tmp_path, windows):
    shim = str(fake_shim(tmp_path, "codex.cmd"))
    a = CodexAdapter()
    assert a.check_available(AgentSpec(adapter="codex", options={"executable": shim})) is None
    bad = AgentSpec(adapter="codex", args=("-c", "x=a|b"), options={"executable": shim})
    assert "batch file" in a.check_available(bad)
    spec = AgentSpec(adapter="codex", options={"executable": shim})
    (tmp_path / "a&b").mkdir()
    (tmp_path / "plain").mkdir()
    with pytest.raises(AdapterError, match="batch file"):
        a.build(make_ctx(tmp_path / "a&b", spec))
    a.build(make_ctx(tmp_path / "plain", spec))


def test_command_batch_shim_checked(tmp_path, windows):
    shim = str(fake_shim(tmp_path, "tool.cmd"))
    a = CommandAdapter()
    msg = a.check_available(AgentSpec(adapter="command", command=(shim, "{prompt}")))
    assert msg and "{prompt} cannot be passed safely" in msg
    assert "batch file" in a.check_available(AgentSpec(adapter="command", command=(shim, "a&b")))
    assert a.check_available(AgentSpec(adapter="command", command=(shim, "{prompt_file}"))) is None
    spec = AgentSpec(adapter="command", command=(shim, "{model}"), model="x^y")
    with pytest.raises(AdapterError, match="batch file"):
        a.build(make_ctx(tmp_path, spec))


@pytest.mark.skipif(os.name != "nt", reason="needs cmd.exe")
def test_claude_batch_shim_end_to_end(tmp_path):
    shim = fake_shim(tmp_path, "claude.cmd")
    marker = tmp_path / "pwned.txt"
    text = f'Line one.\nUse %USERNAME% & echo INJECTED>{marker}\n"quoted" ^ !x!'
    spec = AgentSpec(
        adapter="claude-code",
        model="sonnet",
        options={"executable": str(shim), "append_system_prompt": text},
    )
    assert ClaudeCodeAdapter().check_available(spec) is None
    ctx = make_ctx(tmp_path, spec)
    inv = ClaudeCodeAdapter().build(ctx)
    assert text not in inv.argv
    subprocess.run(inv.argv, cwd=inv.cwd, input=inv.stdin, text=True, check=True, timeout=30)
    got = json.loads((shim.parent / "argv.json").read_text(encoding="utf-8"))
    assert got == inv.argv[1:]
    path = got[got.index("--append-system-prompt-file") + 1]
    assert Path(path).read_bytes().decode("utf-8") == text
    assert not marker.exists()


@pytest.mark.skipif(os.name != "nt", reason="needs cmd.exe")
def test_real_windows_flag_matches_platform():
    assert base.IS_WINDOWS is True and command_mod.IS_WINDOWS is True
