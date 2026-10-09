import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_ab import __version__
from agent_ab.cli import main
from agent_ab.config import load_experiment
from agent_ab.model import TrialRecord
from agent_ab.store import RunStore

PROGRESS_RE = re.compile(r"^\[\s*\d+/\d+\] \S+\s+\S+\s+r\d+\s+(pass|fail|error)\s", re.M)

# Two tasks x two arms x one repeat keeps every run test to a few seconds.
SMALL = ["--repeats", "1", "--only", "fix-slugify", "--only", "roman-numerals"]


def run_cli(capsys, *argv: str) -> tuple[int, str, str]:
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out, err


@pytest.fixture
def demo(tmp_path, capsys) -> Path:
    code, _, _ = run_cli(capsys, "init", tmp_path / "demo")
    assert code == 0
    return tmp_path / "demo"


@pytest.fixture(scope="module")
def finished_run(tmp_path_factory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("cli-run")
    assert main(["init", str(root / "demo")]) == 0
    config = root / "demo" / "experiment.toml"
    run_dir = root / "run"
    assert main(["run", str(config), "--out", str(run_dir), "--quiet", *SMALL]) == 0
    return config, run_dir


# --------------------------------------------------------------------------- basics


def test_version(capsys):
    code, out, _ = run_cli(capsys, "--version")
    assert code == 0
    assert out.strip() == f"agent-ab {__version__}"


def test_module_entry_point_version():
    proc = subprocess.run(
        [sys.executable, "-m", "agent_ab", "--version"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0
    assert __version__ in proc.stdout


def test_no_command_is_usage_error(capsys):
    code, _, err = run_cli(capsys)
    assert code == 2
    assert "usage" in err


def test_unknown_option_is_usage_error(capsys):
    code, _, err = run_cli(capsys, "run", "x.toml", "--jobs", "0")
    assert code == 2
    assert "agent-ab" in err and "error" in err


def test_bad_config_exits_2_without_traceback(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("AGENT_AB_DEBUG", raising=False)
    cfg = tmp_path / "experiment.toml"
    cfg.write_text('name = "x"\nbogus = 1\n', encoding="utf-8")
    code, _, err = run_cli(capsys, "validate", cfg)
    assert code == 2
    assert err.startswith("agent-ab: error: ")
    assert "bogus" in err
    assert "Traceback" not in err


def test_debug_env_prints_traceback(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("AGENT_AB_DEBUG", "1")
    code, _, err = run_cli(capsys, "validate", tmp_path / "missing.toml")
    assert code == 2
    assert "Traceback" in err
    assert "agent-ab: error: " in err


def test_missing_config_exits_2(tmp_path, capsys):
    code, _, err = run_cli(capsys, "run", tmp_path / "nope.toml")
    assert code == 2
    assert "not found" in err


def test_not_a_run_dir_exits_1(tmp_path, capsys):
    for cmd in ("report", "status"):
        code, _, err = run_cli(capsys, cmd, tmp_path)
        assert code == 1
        assert err.startswith("agent-ab: error: ") and "run directory" in err


# --------------------------------------------------------------------------- init / validate


def test_init_prints_next_steps(tmp_path, capsys):
    code, out, _ = run_cli(capsys, "init", tmp_path / "d")
    assert code == 0
    assert "agent-ab run experiment.toml" in out
    assert (tmp_path / "d" / "experiment.toml").is_file()
    assert out.isascii()


def test_init_refuses_non_empty_dir(tmp_path, capsys):
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    code, _, err = run_cli(capsys, "init", tmp_path)
    assert code == 2
    assert err.startswith("agent-ab: error: ") and "--force" in err
    code, _, _ = run_cli(capsys, "init", tmp_path, "--force")
    assert code == 0
    assert (tmp_path / "file.txt").is_file()


def test_validate_summary(demo, capsys):
    code, out, _ = run_cli(capsys, "validate", demo / "experiment.toml")
    assert code == 0
    assert "Planned trials: 4 tasks x 2 arms x 2 repeats = 16" in out
    assert "control *" in out and "arms/with-guide" in out
    assert "available" in out


def test_validate_selection(demo, capsys):
    code, out, err = run_cli(capsys, "validate", demo / "experiment.toml", "--arms", "control",
                             "--only", "fix-*")
    assert code == 0
    assert "1 tasks x 1 arms" in out
    assert "only one arm" in err


def test_validate_unavailable_adapter_is_a_warning(demo, capsys):
    cfg = demo / "experiment.claude-code.toml"
    text = cfg.read_text(encoding="utf-8").replace(
        'max_turns = 30', 'max_turns = 30\nexecutable = "agent-ab-no-such-binary"'
    )
    cfg.write_text(text, encoding="utf-8")
    code, out, err = run_cli(capsys, "validate", cfg)
    assert code == 0
    assert "NOT available" in out
    assert "warning" in err


def test_validate_tasks_on_scaffold(demo, capsys):
    code, out, _ = run_cli(capsys, "validate", demo / "experiment.toml", "--tasks")
    assert code == 0, out
    assert "4 of 4 tasks ok" in out
    assert out.count(" ok") >= 4


def test_validate_tasks_flags_broken_tasks(demo, capsys):
    tasks = demo / "tasks"
    # Already solved: the check passes before the agent does anything.
    shutil.copy(tasks / "roman-numerals" / "solution" / "roman.py",
                tasks / "roman-numerals" / "repo" / "roman.py")
    # Wrong solution: the check fails even with the reference fix.
    shutil.copy(tasks / "fix-slugify" / "repo" / "text_utils.py",
                tasks / "fix-slugify" / "solution" / "text_utils.py")
    # No solution: only the must-fail half can be checked (a warning, not a problem).
    shutil.rmtree(tasks / "merge-intervals" / "solution")
    code, out, err = run_cli(capsys, "validate", demo / "experiment.toml", "--tasks",
                             "--jobs", "2")
    assert code == 1
    assert "roman-numerals: check passes on the untouched repo" in out
    assert "fix-slugify: check fails with the solution applied" in out
    assert "no solution" in out
    assert "merge-intervals" in err
    assert "2 of 4 tasks ok, 2 with problems" in out


# --------------------------------------------------------------------------- run


def test_dry_run_creates_nothing(demo, capsys):
    out_dir = demo / "the-run"
    code, out, err = run_cli(capsys, "run", demo / "experiment.toml", "--dry-run",
                             "--out", out_dir)
    assert code == 0
    assert "16 planned" in err and "dry run" in err
    assert not out_dir.exists() and not (demo / "runs").exists()
    assert out == ""


def test_run_needs_two_arms(demo, capsys):
    code, _, err = run_cli(capsys, "run", demo / "experiment.toml", "--arms", "control")
    assert code == 2
    assert "at least two arms" in err


def test_out_and_resume_are_exclusive(demo, capsys):
    code, _, _ = run_cli(capsys, "run", demo / "experiment.toml", "--out", "a", "--resume", "b")
    assert code == 2


def test_run_completes_and_writes_reports(demo, capsys):
    code, out, err = run_cli(capsys, "run", demo / "experiment.toml", *SMALL, "--jobs", "4")
    assert code == 0, err
    runs = list((demo / "runs").iterdir())
    assert len(runs) == 1 and runs[0].name.startswith("demo-")
    for name in ("report.html", "report.md", "analysis.json"):
        assert (runs[0] / name).is_file()
    assert out.startswith("agent-ab report: demo")
    assert len(PROGRESS_RE.findall(err)) == 4
    assert "trials     4 planned" in err
    assert "wrote" in err and "report.html" in err
    data = json.loads((runs[0] / "analysis.json").read_text(encoding="utf-8"))
    assert data  # parseable
    assert out.isascii() and err.isascii()


def test_run_quiet_has_no_progress_lines(finished_run):
    _, run_dir = finished_run
    assert (run_dir / "report.md").is_file()
    store = RunStore.open(run_dir)
    assert len(store.final_records()) == 4


def test_quiet_suppresses_trial_lines(demo, capsys):
    code, _, err = run_cli(capsys, "run", demo / "experiment.toml", *SMALL, "--quiet",
                           "--only", "parse-duration")
    assert code == 0
    assert not PROGRESS_RE.search(err)


def test_budget_stop_then_resume(demo, capsys):
    cfg = demo / "experiment.toml"
    run_dir = demo / "r"
    # One job and a budget below one trial's cost: exactly one trial runs, then it stops.
    code, _, err = run_cli(capsys, "run", cfg, "--out", run_dir, "--budget", "0.001",
                           "--jobs", "1", *SMALL)
    assert code == 0
    assert "budget" in err and "--resume" in err
    assert "--repeats 1" in err  # the hint reproduces the fingerprint-relevant overrides
    assert len(RunStore.open(run_dir).records()) == 1

    # A different --repeats changes the fingerprint, so resuming must refuse.
    code, _, err = run_cli(capsys, "run", cfg, "--resume", run_dir, "--repeats", "2",
                           "--only", "fix-slugify", "--only", "roman-numerals")
    assert code == 1
    assert "changed" in err

    code, out, err = run_cli(capsys, "run", cfg, "--resume", run_dir, *SMALL)
    assert code == 0, err
    assert len(RunStore.open(run_dir).final_records()) == 4
    assert out.startswith("agent-ab report")
    assert (run_dir / "report.html").is_file()

    # Resuming a finished run runs nothing and still reports.
    code, out, err = run_cli(capsys, "run", cfg, "--resume", run_dir, *SMALL)
    assert code == 0
    assert not PROGRESS_RE.search(err)
    assert len(RunStore.open(run_dir).records()) == 4


def test_ctrl_c_exits_130_with_resume_hint(demo, capsys, monkeypatch):
    import agent_ab.runner as runner

    def interrupted(exp, run_dir, **kwargs):
        if kwargs["options"].dry_run:  # the CLI's silent preflight
            return None
        RunStore.create(run_dir, exp, planned_trials=4)
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "run_experiment", interrupted)
    run_dir = demo / "r"
    code, _, err = run_cli(capsys, "run", demo / "experiment.toml", "--out", run_dir, *SMALL)
    assert code == 130
    assert "interrupted; resume with: agent-ab run" in err
    assert "--resume" in err and str(run_dir) in err


def test_cancelled_summary_exits_130(demo, capsys, monkeypatch):
    import agent_ab.runner as runner

    def cancelled(exp, run_dir, **kwargs):
        if kwargs["options"].dry_run:  # the CLI's silent preflight
            return None
        RunStore.create(run_dir, exp, planned_trials=4)
        return runner.RunSummary(run_dir=run_dir, planned=4, completed=1, errors=0,
                                 skipped_budget=0, cancelled=True, total_cost_usd=0.0,
                                 budget_exhausted=False)

    monkeypatch.setattr(runner, "run_experiment", cancelled)
    code, _, err = run_cli(capsys, "run", demo / "experiment.toml", "--out", demo / "r")
    assert code == 130
    assert "resume with" in err


# --------------------------------------------------------------------------- report


@pytest.mark.parametrize(
    ("fmt", "marker"),
    [("text", "agent-ab report: demo"), ("md", "#"), ("json", "{"), ("html", "<html")],
)
def test_report_formats_to_stdout(finished_run, capsys, fmt, marker):
    _, run_dir = finished_run
    code, out, _ = run_cli(capsys, "report", run_dir, "--format", fmt)
    assert code == 0
    assert marker in out
    if fmt == "json":
        json.loads(out)


def test_report_out_file_and_dir(finished_run, tmp_path, capsys):
    _, run_dir = finished_run
    code, out, err = run_cli(capsys, "report", run_dir, "--format", "html", "--out", tmp_path)
    assert code == 0 and out == ""
    assert (tmp_path / "report.html").read_text(encoding="utf-8").lstrip().startswith("<")
    assert "report.html" in err
    target = tmp_path / "sub" / "r.md"
    code, _, _ = run_cli(capsys, "report", run_dir, "--format", "md", "--out", target)
    assert code == 0 and target.is_file()


def test_report_options(finished_run, capsys):
    _, run_dir = finished_run
    code, out, _ = run_cli(capsys, "report", run_dir, "--baseline", "with-guide",
                           "--alpha", "0.1", "--seed", "3")
    assert code == 0
    assert "vs with-guide" in out
    code, _, err = run_cli(capsys, "report", run_dir, "--baseline", "nope")
    assert code == 2 and "nope" in err
    code, _, _ = run_cli(capsys, "report", run_dir, "--alpha", "2")
    assert code == 2


# --------------------------------------------------------------------------- status / show


def _partial_run(demo: Path) -> Path:
    exp = load_experiment(demo / "experiment.toml")
    run_dir = demo / "partial"
    store = RunStore.create(run_dir, exp, planned_trials=24)

    def rec(tid, attempt, status, cost, error=None, finished="2026-01-01T00:00:0{}Z"):
        task, arm, rep = tid.split("__")
        store.append(TrialRecord(
            trial_id=tid, task=task, arm=arm, repeat=int(rep[1:]), attempt=attempt,
            status=status, passed={"pass": True, "fail": False}.get(status), cost_usd=cost,
            error=error, finished_at=finished.format(attempt),
            artifacts=f"trials/{tid}/attempt-{attempt}",
        ))
        store.attempt_dir(tid, attempt).joinpath("agent.stdout").write_text("x", "utf-8")

    rec("fix-slugify__control__r0", 0, "pass", 0.25)
    rec("fix-slugify__with-guide__r0", 0, "fail", 0.5)
    rec("roman-numerals__control__r0", 0, "error", None, error="rate limit")
    rec("roman-numerals__control__r0", 1, "error", None, error="rate limit again")
    # A truncated final line, as left by a crash mid-write, must not break inspection.
    with open(run_dir / "trials.jsonl", "a", encoding="utf-8") as f:
        f.write('{"trial_id": "trunc')
    return run_dir


def test_status_on_partial_run(demo, capsys):
    run_dir = _partial_run(demo)
    code, out, _ = run_cli(capsys, "status", run_dir)
    assert code == 0
    assert "Trials: 2/24 done (1 pass, 1 fail, 0 error), 22 remaining (1 awaiting a retry)" in out
    assert "spend: $0.75" in out
    assert "Last activity: 2026-01-01T00:00:01Z" in out
    assert "will retry on resume" in out and "rate limit again" in out
    assert re.search(r"control\s+1/12\s+1\s+0\s+0", out)
    assert "not written yet" in out


def test_show_trial(demo, capsys):
    run_dir = _partial_run(demo)
    code, out, _ = run_cli(capsys, "show", run_dir, "roman-numerals__control__r0")
    assert code == 0
    record = json.loads(out.split("\n\n")[0])
    assert record["attempt"] == 1 and record["status"] == "error"
    assert "Attempts (2):" in out
    assert "attempt-0" in out and "attempt-1" in out and "agent.stdout" in out


def test_show_unknown_trial_suggests(demo, capsys):
    run_dir = _partial_run(demo)
    code, _, err = run_cli(capsys, "show", run_dir, "fix-slugfy__control__r0")
    assert code == 2
    assert err.startswith("agent-ab: error: ")
    assert "did you mean" in err and "fix-slugify__control__r0" in err
    code, _, err = run_cli(capsys, "show", run_dir, "parse-duration__control__r1")
    assert code == 2 and "has not run yet" in err


def test_show_finished_trial_lists_artifacts(finished_run, capsys):
    _, run_dir = finished_run
    code, out, _ = run_cli(capsys, "show", run_dir, "fix-slugify__control__r0")
    assert code == 0
    for name in ("prompt.md", "agent.stdout", "check.stdout", "record.json"):
        assert name in out


# --------------------------------------------------------------------------- robustness


def test_termination_signal_cancels_run_and_restores_handler(demo, capsys, monkeypatch):
    import signal
    import time

    import agent_ab.runner as runner

    sig = signal.SIGBREAK if sys.platform == "win32" else signal.SIGTERM
    before = signal.getsignal(sig)

    def killed(exp, run_dir, **kwargs):
        if kwargs["options"].dry_run:
            return None
        RunStore.create(run_dir, exp, planned_trials=4)
        signal.raise_signal(sig)  # Ctrl-Break / console close / kill
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:  # the handler interrupts this wait
            time.sleep(0.01)
        raise AssertionError("the signal did not interrupt the run")

    monkeypatch.setattr(runner, "run_experiment", killed)
    run_dir = demo / "r"
    code, _, err = run_cli(capsys, "run", demo / "experiment.toml", "--out", run_dir, *SMALL)
    assert code == 130
    assert "interrupted; resume with: agent-ab run" in err
    assert signal.getsignal(sig) == before


def test_streams_keep_console_encoding(monkeypatch):
    import io

    from agent_ab import cli

    raw = io.BytesIO()
    utf8 = io.TextIOWrapper(raw, encoding="utf-8", errors="strict")
    monkeypatch.setattr(sys, "stdout", utf8)
    cli._setup_streams()
    assert utf8.encoding == "utf-8" and utf8.errors == "replace"
    cli._out("run dir ü 日本")
    assert raw.getvalue().decode("utf-8").strip() == "run dir ü 日本"

    raw = io.BytesIO()
    legacy = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", legacy)
    cli._setup_streams()
    cli._out("ü 日")  # cannot be encoded: replaced, not a crash
    assert raw.getvalue().decode("cp1252").strip() == "ü ?"


def test_clean_strips_terminal_controls():
    from agent_ab.cli import _clean

    hostile = "a\x1b[2J\x1b]0;title\x07b\x1b]8;;http://x\x1b\\c\x9b31md\x07\x00e\x7f\x85f\tg\nh"
    assert _clean(hostile) == "abcde" + "f\tg\nh"
    assert _clean("plain ü text") == "plain ü text"


@pytest.mark.parametrize("cmd", ["report", "status"])
def test_missing_run_dir_exits_2(tmp_path, capsys, cmd):
    code, out, err = run_cli(capsys, cmd, tmp_path / "nope")
    assert code == 2
    assert err.count("\n") == 1 and "run directory not found" in err
    code, _, err = run_cli(capsys, "show", tmp_path / "nope", "a__b__r0")
    assert code == 2


def test_resume_missing_dir_exits_2_before_header(demo, capsys):
    code, _, err = run_cli(capsys, "run", demo / "experiment.toml", "--resume", demo / "nope")
    assert code == 2
    assert err.count("\n") == 1 and "run directory not found" in err


def test_out_onto_existing_run_exits_2_before_header(finished_run, capsys):
    config, run_dir = finished_run
    code, _, err = run_cli(capsys, "run", config, "--out", run_dir, *SMALL)
    assert code == 2
    assert err.count("\n") == 1 and "already contains a run" in err and "--resume" in err


def test_unavailable_adapter_fails_before_header(demo, capsys):
    cfg = demo / "experiment.claude-code.toml"
    text = cfg.read_text(encoding="utf-8").replace(
        'max_turns = 30', 'max_turns = 30\nexecutable = "agent-ab-no-such-binary"'
    )
    cfg.write_text(text, encoding="utf-8")
    code, _, err = run_cli(capsys, "run", cfg, "--out", demo / "r")
    assert code == 1
    assert "agent-ab-no-such-binary" in err
    assert "experiment " not in err and "run dir" not in err
    assert not (demo / "r").exists()


def test_incomplete_run_json_is_a_clear_error(tmp_path, capsys):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text('{"tool": "agent-ab", "schema": 1}', encoding="utf-8")
    for argv in (["report", run_dir], ["status", run_dir], ["show", run_dir, "a__b__r0"]):
        code, _, err = run_cli(capsys, *argv)
        assert code == 1
        assert "run.json is incomplete" in err and "baseline" in err and "None" not in err


@pytest.mark.parametrize("name", ["con", "NUL.html", "aux.md", "com1.txt", "LPT9", "sub/prn.json"])
def test_report_out_reserved_device_name(finished_run, tmp_path, capsys, name):
    _, run_dir = finished_run
    code, _, err = run_cli(capsys, "report", run_dir, "--out", str(tmp_path / name))
    assert code == 2
    assert "reserved device name" in err


@pytest.mark.parametrize(
    ("flag", "value"),
    [("--budget", "0"), ("--budget", "-1"), ("--budget", "nan"), ("--jobs", "0"),
     ("--jobs", "x"), ("--repeats", "0"), ("--repeats", "-2")],
)
def test_numeric_flags_must_be_positive(demo, capsys, flag, value):
    code, _, err = run_cli(capsys, "run", demo / "experiment.toml", flag, value)
    assert code == 2
    assert flag in err and "Traceback" not in err


def _hostile_run(demo: Path) -> Path:
    exp = load_experiment(demo / "experiment.toml")
    run_dir = demo / "hostile"
    RunStore.create(run_dir, exp, planned_trials=24)
    lines = [
        {"trial_id": "fix-slugify__control__r0", "task": "fix-slugify", "arm": "control",
         "repeat": 0, "attempt": 2, "status": "error", "cost_usd": 10**400,
         "error": "boom\x1b]0;owned\x07\x1b[2J\x1b[1A hidden", "artifacts": "../../.."},
        {"trial_id": "x\x1b[31m__with-guide__r0", "task": "x\x1b[31m", "arm": "with-guide",
         "repeat": 0, "attempt": 2, "status": "error", "cost_usd": 1e308, "duration_s": 1e300,
         "error": "\x9b2J\x00bad"},
    ]
    with open(run_dir / "trials.jsonl", "a", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return run_dir


def test_status_survives_hostile_records(demo, capsys):
    run_dir = _hostile_run(demo)
    code, out, err = run_cli(capsys, "status", run_dir)
    assert code == 0, err
    assert "\x1b" not in out and "\x07" not in out and "\x9b" not in out and "\x00" not in out
    assert "spend: >$1e6" in out
    assert "boom" in out and "hidden" in out


def test_show_refuses_artifacts_outside_run_dir(demo, capsys):
    run_dir = _hostile_run(demo)
    code, out, err = run_cli(capsys, "show", run_dir, "fix-slugify__control__r0")
    assert code == 0
    assert "outside the run directory" in err
    assert "(not listed)" in out
    assert "\x1b" not in out + err


def test_number_formatting_caps():
    from agent_ab.cli import _fmt_cost, _fmt_seconds, _total

    assert _fmt_cost(None) == "-" and _fmt_cost("x") == "-"
    assert _fmt_cost(10**400) == ">$1e6" and _fmt_cost(float("inf")) == ">$1e6"
    assert _fmt_cost(-(10**400)) == "<-$1e6" and _fmt_cost(float("nan")) == "-"
    assert _fmt_cost(0.25) == "$0.250"
    assert _fmt_seconds(1e300) == ">1e6s" and _fmt_seconds(None) == "-"
    assert _fmt_seconds(2.25) == "2.2s" or _fmt_seconds(2.25) == "2.3s"
    assert _total([None, 10**400, 1.0]) == float("inf")
    assert _total([1.0, None, 2]) == 3.0


# --------------------------------------------------------------------------- power


def test_power_json_output(capsys):
    code, out, err = run_cli(
        capsys, "power", "--effect", "20", "--tasks", "10,20", "--repeats", "1",
        "--sims", "20", "--seed", "5", "--format", "json",
    )
    assert code == 0, err
    data = json.loads(out)
    assert data["model"]["name"] == "beta"
    assert [(r["tasks"], r["repeats"]) for r in data["rows"]] == [(10, 1), (20, 1)]
    assert data["false_positive"]["effect_pts"] == 0.0
    assert {"effect_pts", "design"} <= set(data["recommendations"][0])


def test_power_text_output(capsys):
    code, out, _ = run_cli(capsys, "power", "--tasks", "10", "--repeats", "1", "--sims", "10")
    assert code == 0
    assert "Power plan" in out and "Smallest design with at least 80% power:" in out


@pytest.mark.parametrize(
    ("flag", "value"),
    [("--effect", "0"), ("--effect", "100"), ("--effect", "10,x"), ("--tasks", "10,,20"),
     ("--tasks", "-5"), ("--repeats", "0"), ("--alpha", "2"), ("--sims", "0"),
     ("--seed", "1.5")],
)
def test_power_bad_values_exit_2_with_one_line(capsys, flag, value):
    code, out, err = run_cli(capsys, "power", flag, value)
    assert code == 2
    assert out == ""
    assert err.count("\n") == 1 and err.startswith("agent-ab: error: ") and flag in err


def test_power_missing_run_dir_exits_2(tmp_path, capsys):
    code, _, err = run_cli(capsys, "power", tmp_path / "nope", "--sims", "5")
    assert code == 2 and "run directory not found" in err
