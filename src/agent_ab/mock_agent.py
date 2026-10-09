"""Offline, deterministic stand-in for a coding agent (``python -m agent_ab.mock_agent``).

Given a seed it decides whether to "solve" the task by copying the task's reference solution
into the workspace, how much it "spent", and whether to simulate a crash or an infrastructure
error. It reports usage through ``<artifacts>/usage.json``, the same contract as the command
adapter. Used by the demo scaffold and the test suite; never touches the network.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

DEFAULTS: dict[str, Any] = {
    "solve_rate": 0.5,
    "task_rates": {},
    "cost_usd": 0.01,
    "duration_s": 0.0,
    "tokens": 1000,
    "fail_mode": "revert",
    "infra_error_rate": 0.0,
    "crash_rate": 0.0,
}

CRASH_EXIT_CODE = 3
INFRA_EXIT_CODE = 1
BROKEN_MARKER = "# broken by the agent-ab mock agent\n"


class Decision(NamedTuple):
    """What the mock agent will do for one seed."""

    crash: bool
    infra_error: bool
    solve: bool
    cost_usd: float
    duration_s: float
    input_tokens: int
    output_tokens: int
    turns: int


def _pick(value: Any, r: float) -> float:
    """A scalar, or a point inside a ``[lo, hi]`` range chosen by ``r``."""
    if isinstance(value, list | tuple):
        lo, hi = float(value[0]), float(value[1])
        return lo + (hi - lo) * r
    return float(value)


def decide(seed: int, options: Mapping[str, Any], task_id: str = "") -> Decision:
    """Pure decision function: identical inputs always give the identical decision."""
    opts = {**DEFAULTS, **options}
    rng = random.Random(seed)
    # Every draw happens unconditionally and in a fixed order, so changing one rate
    # never reshuffles the outcome of another.
    r_crash, r_infra, r_solve, r_cost, r_dur, r_tok, r_turns = (rng.random() for _ in range(7))
    rates = opts.get("task_rates") or {}
    rate = float(rates.get(task_id, opts["solve_rate"]))
    tokens = int(opts["tokens"])
    scaled = max(int(tokens * (0.75 + 0.5 * r_tok)), 0)
    return Decision(
        crash=r_crash < float(opts["crash_rate"]),
        infra_error=r_infra < float(opts["infra_error_rate"]),
        solve=r_solve < rate,
        cost_usd=round(_pick(opts["cost_usd"], r_cost), 6),
        duration_s=max(_pick(opts["duration_s"], r_dur), 0.0),
        input_tokens=scaled,
        output_tokens=scaled // 5,
        turns=1 + int(r_turns * 5),
    )


def _write_usage(artifacts: Path, data: dict[str, Any]) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "usage.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def _break(workspace: Path, solution: Path | None) -> str:
    """Overwrite a file the solution would touch, so the hidden check fails."""
    files = sorted(p for p in solution.rglob("*") if p.is_file()) if solution else []
    rel = files[0].relative_to(solution) if files else Path("mock_agent_output.txt")
    target = workspace / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(BROKEN_MARKER, encoding="utf-8", newline="\n")
    return rel.as_posix()


def run(
    *,
    workspace: Path,
    artifacts: Path,
    seed: int,
    task_id: str = "",
    solution: Path | None = None,
    options: Mapping[str, Any] | None = None,
) -> int:
    """Act out one trial and return the process exit code."""
    opts = {**DEFAULTS, **(options or {})}
    d = decide(seed, opts, task_id)
    if d.duration_s:
        time.sleep(d.duration_s)
    if d.crash:
        print("mock agent: simulated crash", file=sys.stderr)
        return CRASH_EXIT_CODE
    usage: dict[str, Any] = {
        "cost_usd": d.cost_usd,
        "input_tokens": d.input_tokens,
        "output_tokens": d.output_tokens,
        "turns": d.turns,
    }
    if d.infra_error:
        usage["infra_error"] = "simulated infrastructure error (mock agent)"
        _write_usage(artifacts, usage)
        print("mock agent: simulated infrastructure error", file=sys.stderr)
        return INFRA_EXIT_CODE
    has_solution = solution is not None and solution.is_dir()
    if d.solve and has_solution:
        shutil.copytree(solution, workspace, dirs_exist_ok=True)
        usage["final_message"] = "Applied the reference solution."
    elif opts["fail_mode"] == "break":
        rel = _break(workspace, solution if has_solution else None)
        usage["final_message"] = f"Changed {rel} (incorrectly)."
    else:
        usage["final_message"] = "Gave up without changing anything."
    _write_usage(artifacts, usage)
    print(usage["final_message"])
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point used by the mock adapter."""
    p = argparse.ArgumentParser(prog="python -m agent_ab.mock_agent", description=__doc__)
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--artifacts", type=Path, required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--task-id", default="")
    p.add_argument("--solution", type=Path, default=None)
    p.add_argument("--options", default="{}", help="JSON object of mock adapter options")
    args = p.parse_args(argv)
    try:
        options = json.loads(args.options)
    except ValueError:
        p.error("--options must be a JSON object")
    if not isinstance(options, dict):
        p.error("--options must be a JSON object")
    return run(
        workspace=args.workspace,
        artifacts=args.artifacts,
        seed=args.seed,
        task_id=args.task_id,
        solution=args.solution,
        options=options,
    )


if __name__ == "__main__":
    sys.exit(main())
