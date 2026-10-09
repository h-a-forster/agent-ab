"""Adapter for the built-in offline mock agent (see ``agent_ab.mock_agent``)."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_ab.adapters.base import Adapter
from agent_ab.adapters.command import USAGE_FILE, _is_number, _read_usage_file
from agent_ab.model import AgentInvocation, AgentSpec, AgentUsage, ProcResult, TrialContext

_RATES = ("solve_rate", "infra_error_rate", "crash_rate")
_RANGES = ("cost_usd", "duration_s")
_FAIL_MODES = frozenset({"revert", "break"})

# Lets ``-m agent_ab.mock_agent`` import even when agent-ab runs from a source checkout.
_PACKAGE_PARENT = str(Path(__file__).resolve().parents[2])


def _is_rate(v: Any) -> bool:
    return _is_number(v) and 0 <= v <= 1


def _range_problem(key: str, v: Any) -> str | None:
    if _is_number(v) and v >= 0:
        return None
    if (
        isinstance(v, list | tuple)
        and len(v) == 2
        and all(_is_number(x) and x >= 0 for x in v)
        and v[0] <= v[1]
    ):
        return None
    return f"option {key!r} must be a non-negative number or a [low, high] range"


class MockAdapter(Adapter):
    """Runs the deterministic offline mock agent; no network, no API keys, no cost."""

    name = "mock"
    option_keys = frozenset(
        {
            "solve_rate",
            "task_rates",
            "cost_usd",
            "duration_s",
            "tokens",
            "fail_mode",
            "infra_error_rate",
            "crash_rate",
        }
    )

    def validate(self, spec: AgentSpec) -> list[str]:
        problems = super().validate(spec)
        o = spec.options
        for key in _RATES:
            if key in o and not _is_rate(o[key]):
                problems.append(f"option {key!r} must be a number between 0 and 1")
        for key in _RANGES:
            if key in o and (msg := _range_problem(key, o[key])):
                problems.append(msg)
        if "tokens" in o:
            t = o["tokens"]
            if not (isinstance(t, int) and not isinstance(t, bool) and t >= 0):
                problems.append("option 'tokens' must be a non-negative integer")
        if "fail_mode" in o and o["fail_mode"] not in _FAIL_MODES:
            problems.append("option 'fail_mode' must be 'revert' or 'break'")
        if "task_rates" in o:
            rates = o["task_rates"]
            if not isinstance(rates, Mapping) or not all(
                isinstance(k, str) and _is_rate(v) for k, v in rates.items()
            ):
                problems.append("option 'task_rates' must map task ids to numbers between 0 and 1")
        return problems

    def build(self, ctx: TrialContext) -> AgentInvocation:
        argv = [
            sys.executable,
            "-m",
            "agent_ab.mock_agent",
            "--workspace",
            str(ctx.workspace),
            "--artifacts",
            str(ctx.artifacts),
            "--seed",
            str(ctx.seed),
            "--task-id",
            ctx.task.id,
            "--options",
            json.dumps(dict(ctx.spec.options), sort_keys=True),
        ]
        if ctx.task.solution is not None:
            argv += ["--solution", str(ctx.task.solution)]
        argv += list(ctx.spec.args)
        env = dict(ctx.spec.env)
        existing = env.get("PYTHONPATH", os.environ.get("PYTHONPATH", ""))
        env["PYTHONPATH"] = os.pathsep.join(p for p in (_PACKAGE_PARENT, existing) if p)
        return AgentInvocation(argv=argv, env=env, stdin=None, cwd=ctx.workspace)

    def parse(self, ctx: TrialContext, result: ProcResult) -> AgentUsage:
        return _read_usage_file(ctx.artifacts / USAGE_FILE)
