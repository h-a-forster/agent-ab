from __future__ import annotations

import math
import random
from dataclasses import asdict

import pytest

from agent_ab.model import Interval, TrialRecord, trial_id
from agent_ab.stats import (
    analyze,
    bootstrap_mean_ci,
    holm,
    paired_bootstrap_diff,
    paired_ratio_ci,
    sign_flip_test,
    wilson_interval,
)

N_BOOT = 400  # small for speed; the methods are the same at 10 000


def rec(task, arm, repeat=0, status="pass", attempt=0, cost=0.1, dur=10.0, **kw) -> TrialRecord:
    return TrialRecord(
        trial_id=trial_id(task, arm, repeat),
        task=task,
        arm=arm,
        repeat=repeat,
        attempt=attempt,
        status=status,
        passed=None if status == "error" else status == "pass",
        cost_usd=cost,
        duration_s=dur,
        **kw,
    )


def meta(arms=("control", "treat"), planned=0, baseline=None):
    return {
        "experiment": "exp",
        "baseline": baseline or arms[0],
        "planned_trials": planned,
        "config": {"arms": [{"name": a} for a in arms]},
    }


def grid(n_tasks, repeats, outcome, arms=("control", "treat"), cost=None):
    """outcome(task_index, arm, repeat) -> bool."""
    out = []
    for i in range(n_tasks):
        for arm in arms:
            for r in range(repeats):
                c = cost(i, arm) if cost else 0.1
                out.append(
                    rec(f"t{i:02d}", arm, r, "pass" if outcome(i, arm, r) else "fail", cost=c)
                )
    return out


# --------------------------------------------------------------------------- wilson


@pytest.mark.parametrize(
    ("k", "n", "low", "high"),
    [
        (0, 10, 0.0, 0.2775),
        (5, 10, 0.2366, 0.7634),
        (10, 10, 0.7225, 1.0),
        (1, 10, 0.0179, 0.4041),
        (81, 263, 0.2553, 0.3662),
    ],
)
def test_wilson_known_values(k, n, low, high):
    lo, hi = wilson_interval(k, n)
    assert lo == pytest.approx(low, abs=1e-4)
    assert hi == pytest.approx(high, abs=1e-4)


def test_paired_ratio_skipped_fraction():
    from agent_ab.stats import _paired_ratio_counted

    ci, skipped = _paired_ratio_counted([0.0] * 9 + [1.0], [1.0] * 10, n_boot=2000, alpha=0.05,
                                        rng=1)
    assert ci.estimate == pytest.approx(10.0)
    assert skipped == pytest.approx(0.9**10, abs=0.05)
    assert _paired_ratio_counted([1.0, 2.0], [1.0, 1.0], n_boot=100, alpha=0.05, rng=1)[1] == 0


def test_wilson_edge_cases():
    assert wilson_interval(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError):
        wilson_interval(3, 2)


# --------------------------------------------------------------------------- bootstrap


def test_bootstrap_degenerate():
    assert bootstrap_mean_ci([], rng=1) == Interval(None, None, None)
    assert bootstrap_mean_ci([0.4], rng=1) == Interval(0.4, None, None)
    assert bootstrap_mean_ci([0.5] * 6, n_boot=50, rng=1) == Interval(0.5, 0.5, 0.5)


def test_bootstrap_deterministic_and_contains_estimate():
    vals = [0.0, 0.2, 0.5, 1.0, 0.7, 0.3]
    a = bootstrap_mean_ci(vals, n_boot=N_BOOT, rng=7)
    b = bootstrap_mean_ci(vals, n_boot=N_BOOT, rng=random.Random(7))
    assert a == b
    assert a.low <= a.estimate <= a.high
    assert a.estimate == pytest.approx(sum(vals) / len(vals))


def test_bootstrap_coverage_sanity():
    # Percentile bootstrap slightly undercovers at small n; the tolerance is deliberately loose.
    gen = random.Random(123)
    hits = 0
    sims = 300
    for s in range(sims):
        data = [gen.gauss(1.0, 2.0) for _ in range(25)]
        ci = bootstrap_mean_ci(data, n_boot=300, rng=s)
        hits += ci.low <= 1.0 <= ci.high
    assert 0.88 <= hits / sims <= 0.99


def test_paired_bootstrap_diff():
    ci = paired_bootstrap_diff([0.0, 0.5, 1.0], [1.0, 1.0, 1.0], n_boot=N_BOOT, rng=3)
    assert ci.estimate == pytest.approx(0.5)
    assert 0.0 <= ci.low <= ci.high <= 1.0
    with pytest.raises(ValueError):
        paired_bootstrap_diff([1.0], [1.0, 2.0])


def test_paired_ratio_ci():
    ci = paired_ratio_ci([1.0, 2.0, 3.0], [2.0, 4.0, 6.0], n_boot=N_BOOT, rng=3)
    assert ci == Interval(pytest.approx(2.0), pytest.approx(2.0), pytest.approx(2.0))
    assert paired_ratio_ci([0.0, 0.0], [1.0, 2.0], rng=1) == Interval(None, None, None)
    assert paired_ratio_ci([], [], rng=1) == Interval(None, None, None)
    assert paired_ratio_ci([2.0], [3.0], rng=1) == Interval(1.5, None, None)
    # A zero baseline in some tasks is fine as long as the mean is positive.
    ci = paired_ratio_ci([0.0, 1.0, 1.0, 2.0], [1.0, 1.0, 2.0, 2.0], n_boot=N_BOOT, rng=2)
    assert ci.estimate == pytest.approx(1.5)
    assert ci.low is not None and ci.low <= ci.estimate <= ci.high


# --------------------------------------------------------------------------- sign flip


def brute_force(diffs):
    n = len(diffs)
    obs = abs(math.fsum(diffs)) / n
    hits = total = 0
    for mask in range(2**n):
        s = math.fsum(-d if mask >> i & 1 else d for i, d in enumerate(diffs))
        hits += abs(s) / n >= obs - 1e-12
        total += 1
    return hits / total


@pytest.mark.parametrize(
    ("diffs", "p"),
    [
        ([1, 1, 1], 0.25),
        ([1, 1, 1, 1, 1], 0.0625),
        ([1, 1, 1, -1], 0.625),
        ([1, 1, 1, 0], 0.25),
        ([0.5, -0.5], 1.0),
        ([0, 0, 0], 1.0),
    ],
)
def test_sign_flip_exact(diffs, p):
    assert sign_flip_test(diffs) == pytest.approx(p)


def test_sign_flip_matches_brute_force_with_float_noise():
    diffs = [0.1, 0.2, -0.3, 1 / 3, 2 / 3, -0.1, 0.7, 0.0, 0.05]
    assert sign_flip_test(diffs) == pytest.approx(brute_force(diffs))


def test_sign_flip_empty_is_nan():
    assert math.isnan(sign_flip_test([]))


def test_sign_flip_monte_carlo():
    # 20 identical positive diffs: exact p = 2 / 2**20, Monte Carlo floor is 1 / (n + 1).
    p = sign_flip_test([1.0] * 20, n_perm=2000, rng=1)
    assert p == pytest.approx(1 / 2001, abs=2 / 2001)
    assert p > 0
    gen = random.Random(5)
    diffs = [gen.choice([-1.0, -0.5, 0.5, 1.0]) + 0.2 for _ in range(17)]
    exact = brute_force(diffs)
    mc = sign_flip_test(diffs, n_perm=4000, rng=9)
    assert mc == pytest.approx(exact, abs=0.03)
    assert sign_flip_test(diffs, n_perm=500, rng=9) == sign_flip_test(diffs, n_perm=500, rng=9)


# --------------------------------------------------------------------------- holm


def test_holm_textbook():
    adj = holm([0.01, 0.04, 0.03, 0.005])
    assert adj == pytest.approx([0.03, 0.06, 0.06, 0.02])


def test_holm_none_cap_and_monotone():
    adj = holm([None, 0.5, 0.01, float("nan"), 0.6])
    assert adj[0] is None and adj[3] is None
    assert adj[2] == pytest.approx(0.03)  # family size 3, not 5
    assert adj[1] == pytest.approx(1.0) and adj[4] == pytest.approx(1.0)
    assert holm([]) == []
    assert holm([0.02, 0.02]) == pytest.approx([0.04, 0.04])


# --------------------------------------------------------------------------- analyze


def test_analyze_clear_win():
    records = grid(12, 3, lambda i, arm, r: arm == "treat" or i % 4 == 0)
    a = analyze(meta(), records, n_boot=N_BOOT)
    (c,) = a.comparisons
    assert c.verdict == "better"
    assert c.paired_tasks == 12 and c.tasks_better == 9 and c.tasks_tied == 3
    assert c.pass_rate_diff.estimate == pytest.approx(0.75)
    assert c.pass_rate_diff.low > 0
    assert c.p_value == pytest.approx(2 / 2**9)
    assert c.p_value_adjusted == pytest.approx(c.p_value)
    control, treat = a.arms
    assert (control.arm, treat.arm) == ("control", "treat")
    assert treat.passes == 36 and treat.trials == 36 and treat.tasks == 12
    assert treat.pass_rate.estimate == 1.0
    assert control.pass_rate_wilson.estimate == pytest.approx(9 / 36)
    assert a.flaky_tasks == []
    assert a.completed_trials == 72 and a.error_trials == 0


def test_analyze_clear_loss_and_order_follows_config():
    records = grid(10, 2, lambda i, arm, r: arm == "control")
    a = analyze(meta(arms=("treat", "control"), baseline="control"), records, n_boot=N_BOOT)
    assert [s.arm for s in a.arms] == ["treat", "control"]
    assert a.comparisons[0].verdict == "worse"


def test_analyze_identical_arms():
    records = grid(8, 2, lambda i, arm, r: i % 2 == 0)
    a = analyze(meta(), records, n_boot=N_BOOT)
    (c,) = a.comparisons
    assert c.verdict == "no detectable difference"
    assert c.p_value == 1.0
    assert c.pass_rate_diff == Interval(0.0, 0.0, 0.0)
    assert c.cost_ratio.estimate == pytest.approx(1.0)


def test_analyze_single_task_insufficient():
    records = grid(1, 5, lambda i, arm, r: arm == "treat")
    a = analyze(meta(), records, n_boot=N_BOOT)
    (c,) = a.comparisons
    assert c.verdict == "insufficient data"
    assert c.pass_rate_diff == Interval(1.0, None, None)
    assert a.arms[1].pass_rate == Interval(1.0, None, None)
    assert any("only one task" in n for n in a.notes)


def test_analyze_few_tasks_note():
    records = grid(3, 2, lambda i, arm, r: arm == "treat" and (i > 0 or r == 0))
    a = analyze(meta(), records, n_boot=N_BOOT)
    # Three tasks all better: exact p = 0.25, so never "better" with alpha 0.05.
    assert a.comparisons[0].verdict == "no detectable difference"
    (note,) = [n for n in a.notes if n.startswith("treat vs control:")]
    assert "too narrow" in note and "permutation test" in note
    assert "no result can reach p < 0.05" in note and "smallest possible p is 0.25" in note
    assert "wide" not in note


@pytest.mark.parametrize(("n_tasks", "floor"), [(5, True), (6, False), (19, False)])
def test_analyze_few_tasks_p_floor(n_tasks, floor):
    # Mixed differences so the degenerate-data note does not apply.
    records = grid(n_tasks, 2, lambda i, arm, r: arm == "treat" and (i > 0 or r == 0))
    a = analyze(meta(), records, n_boot=N_BOOT)
    (note,) = [n for n in a.notes if n.startswith("treat vs control:")]
    assert "too narrow" in note
    assert ("smallest possible p is 0.0625" in note) == floor
    assert ("no result can reach" in note) == floor


def test_analyze_many_tasks_no_small_sample_note():
    records = grid(20, 2, lambda i, arm, r: arm == "treat" and (i > 0 or r == 0))
    a = analyze(meta(), records, n_boot=N_BOOT)
    assert not any(n.startswith("treat vs control:") for n in a.notes)


def test_analyze_few_tasks_p_floor_follows_alpha():
    records = grid(6, 2, lambda i, arm, r: arm == "treat" and (i > 0 or r == 0))
    a = analyze(meta(), records, n_boot=N_BOOT, alpha=0.03)  # 2**-5 = 0.03125 >= alpha
    assert any("no result can reach p < 0.03 " in n for n in a.notes)


@pytest.mark.parametrize(
    ("outcome", "pts"),
    [
        (lambda i, arm, r: True, "+0.0 pts"),  # all pass in both arms
        (lambda i, arm, r: False, "+0.0 pts"),  # all fail in both arms
        (lambda i, arm, r: arm == "treat", "+100.0 pts"),
    ],
)
def test_analyze_degenerate_note(outcome, pts):
    a = analyze(meta(), grid(20, 3, outcome), n_boot=N_BOOT)
    c = a.comparisons[0]
    assert c.pass_rate_diff.low == c.pass_rate_diff.high  # zero-width interval
    (note,) = [n for n in a.notes if n.startswith("treat vs control:")]
    assert f"same difference ({pts})" in note
    assert "no variation across tasks" in note and "not informative" in note
    assert "too narrow" not in note


def test_analyze_degenerate_two_tasks_mentions_p_floor():
    a = analyze(meta(), grid(2, 3, lambda i, arm, r: arm == "treat"), n_boot=N_BOOT)
    (note,) = [n for n in a.notes if n.startswith("treat vs control:")]
    assert "not informative" in note and "smallest possible p is 0.5" in note
    assert "wide" not in note


def test_analyze_wilson_follows_alpha():
    records = grid(6, 2, lambda i, arm, r: r == 0)
    wide = analyze(meta(), records, n_boot=50, alpha=0.01).arms[0].pass_rate_wilson
    narrow = analyze(meta(), records, n_boot=50, alpha=0.2).arms[0].pass_rate_wilson
    z99, z80 = 2.5758293035489, 1.2815515655446
    assert (wide.low, wide.high) == pytest.approx(wilson_interval(6, 12, z=z99))
    assert (narrow.low, narrow.high) == pytest.approx(wilson_interval(6, 12, z=z80))
    assert wide.low < narrow.low < narrow.high < wide.high


def test_analyze_ratio_note_when_baseline_cost_mostly_zero():
    # Baseline cost is zero on all but one of 10 tasks: about 35% of resamples miss that task.
    records = grid(
        10, 1, lambda i, arm, r: True,
        cost=lambda i, arm: 1.0 if arm == "treat" else (2.0 if i == 0 else 0.0),
    )
    a = analyze(meta(), records, n_boot=N_BOOT)
    assert a.comparisons[0].cost_ratio.estimate == pytest.approx(5.0)
    notes = [n for n in a.notes if "ratio interval is unreliable" in n]
    assert len(notes) == 1 and "baseline cost is mostly zero" in notes[0]


def test_analyze_no_ratio_note_with_positive_costs():
    records = grid(10, 1, lambda i, arm, r: True, cost=lambda i, arm: 0.1 + i)
    a = analyze(meta(), records, n_boot=N_BOOT)
    assert not any("unreliable" in n for n in a.notes)


def test_analyze_errors_excluded_and_retries():
    records = grid(6, 1, lambda i, arm, r: True)
    records.append(rec("t00", "treat", 1, "error", cost=None))  # never recovered
    records.append(rec("t01", "treat", 1, "error", attempt=0, cost=0.5))
    records.append(rec("t01", "treat", 1, "fail", attempt=1, cost=0.2))  # retry wins
    records.append(rec("t02", "treat", 1, "pass", attempt=2))
    records.append(rec("t02", "treat", 1, "error", attempt=1))  # out of order, earlier attempt
    a = analyze(meta(planned=15), records, n_boot=N_BOOT)
    treat = a.arms[1]
    assert treat.errors == 1
    assert treat.trials == 8 and treat.passes == 7
    assert a.error_trials == 1 and a.completed_trials == 14
    assert a.notes[0].startswith("1 trial excluded as infrastructure errors")
    cell = next(c for c in a.cells if c.task == "t00" and c.arm == "treat")
    assert (cell.trials, cell.passes, cell.errors) == (1, 1, 1)
    assert a.flaky_tasks == ["t01"]
    # Spend counts every attempt, including errored and superseded ones.
    assert a.total_cost_usd == pytest.approx(0.1 * 12 + 0.5 + 0.2 + 0.1 + 0.1)
    assert not any("incomplete" in n for n in a.notes)  # 15 planned, 15 trials finished
    assert any("range from 1 to 2" in n for n in a.notes)


def test_analyze_incomplete_note_only_when_short():
    records = grid(4, 1, lambda i, arm, r: True)
    assert not any("incomplete" in n for n in analyze(meta(planned=8), records, n_boot=50).notes)
    assert any("8 of 10 planned" in n for n in analyze(meta(planned=10), records, n_boot=50).notes)


def test_analyze_missing_cost():
    records = grid(
        6, 2, lambda i, arm, r: r == 0, cost=lambda i, arm: None if arm == "treat" else 0.2
    )
    a = analyze(meta(), records, n_boot=N_BOOT)
    control, treat = a.arms
    assert treat.mean_cost_usd == Interval(None, None, None)
    assert treat.total_cost_usd is None and treat.cost_per_pass_usd is None
    assert control.total_cost_usd == pytest.approx(2.4)
    assert control.cost_per_pass_usd == pytest.approx(2.4 / 6)
    assert a.comparisons[0].cost_ratio == Interval(None, None, None)
    assert any("Cost was not reported for arm treat" in n for n in a.notes)
    assert a.flaky_tasks == [f"t{i:02d}" for i in range(6)]


def test_analyze_cost_ratio_and_zero_passes():
    records = grid(
        6,
        1,
        lambda i, arm, r: arm == "treat",
        cost=lambda i, arm: (i + 1) * (3.0 if arm == "treat" else 1.0),
    )
    a = analyze(meta(), records, n_boot=N_BOOT)
    c = a.comparisons[0]
    assert c.cost_ratio == Interval(pytest.approx(3.0), pytest.approx(3.0), pytest.approx(3.0))
    assert a.arms[0].cost_per_pass_usd is None  # zero passes
    assert a.arms[0].mean_cost_usd.estimate == pytest.approx(3.5)


def test_analyze_tasks_in_one_arm_and_unknown_baseline():
    records = grid(5, 1, lambda i, arm, r: True)
    records.append(rec("extra", "control"))
    a = analyze(meta(), records, n_boot=N_BOOT)
    assert a.comparisons[0].paired_tasks == 5
    assert any("extra" in n and "only some arms" in n for n in a.notes)
    with pytest.raises(ValueError):
        analyze(meta(), records, baseline="nope")


def test_analyze_baseline_override_and_holm_across_arms():
    arms = ("a", "b", "c")
    records = grid(10, 1, lambda i, arm, r: arm != "a" or i < 2, arms=arms)
    a = analyze(meta(arms=arms), records, baseline="b", n_boot=N_BOOT)
    assert a.baseline == "b"
    assert [c.arm for c in a.comparisons] == ["a", "c"]
    ca, cc = a.comparisons
    assert ca.p_value == pytest.approx(2 / 2**8)
    assert ca.p_value_adjusted == pytest.approx(2 * ca.p_value)  # family of two comparisons
    assert cc.p_value == 1.0 and cc.p_value_adjusted == 1.0
    assert cc.verdict == "no detectable difference" and ca.verdict == "worse"


def test_analyze_deterministic_for_seed():
    gen = random.Random(0)
    records = grid(
        9,
        3,
        lambda i, arm, r: gen.random() < (0.7 if arm == "treat" else 0.4),
        cost=lambda i, arm: round(0.1 + 0.05 * i, 3),
    )
    x = asdict(analyze(meta(), records, seed=4, n_boot=N_BOOT))
    y = asdict(analyze(meta(), list(reversed(records)), seed=4, n_boot=N_BOOT))
    assert x == y
    z = asdict(analyze(meta(), records, seed=5, n_boot=N_BOOT))
    assert (
        z["comparisons"][0]["pass_rate_diff"]["estimate"]
        == x["comparisons"][0]["pass_rate_diff"]["estimate"]
    )


def test_analyze_empty_records():
    a = analyze(meta(planned=4), [], n_boot=N_BOOT)
    assert a.comparisons[0].verdict == "insufficient data"
    assert a.comparisons[0].p_value is None
    assert a.arms[0].pass_rate == Interval(None, None, None)
    assert a.total_cost_usd is None


def test_records_outside_the_plan_are_ignored():
    from agent_ab.model import TrialRecord
    from agent_ab.stats import analyze

    meta = {
        "experiment": "e", "baseline": "a", "planned_trials": 4,
        "config": {
            "arms": [{"name": "a"}, {"name": "b"}],
            "tasks": [{"id": "t1"}, {"id": "t2"}],
            "repeats": 1,
        },
    }

    def rec(task, arm, repeat=0, status="pass"):
        return TrialRecord(
            trial_id=f"{task}__{arm}__r{repeat}", task=task, arm=arm, repeat=repeat,
            attempt=0, status=status, passed=status == "pass",
        )

    planned = [rec(t, a) for t in ("t1", "t2") for a in ("a", "b")]
    stray = [rec("old-task", "a"), rec("t1", "zz"), rec("t1", "a", repeat=5, status="fail")]
    a = analyze(meta, planned + stray, n_boot=200)
    assert a.completed_trials == 4
    assert any("do not belong" in n for n in a.notes)
    assert {s.arm for s in a.arms} == {"a", "b"}
