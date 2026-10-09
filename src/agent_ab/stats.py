"""Statistics for agent-ab: interval estimates, paired tests and the run analysis.

Design notes. Tasks are the unit of replication: repeats of one task under one arm share the
same prompt, repository and check, so their outcomes are correlated. Treating every trial as
independent would overstate precision. Hence pass rates are task-macro means with a cluster
(task-level) bootstrap, and arms are compared with paired statistics over per-task differences
(a bootstrap CI and a sign-flip permutation test). Everything is stdlib-only and deterministic
for a given seed.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Iterable, Sequence
from statistics import fmean

from .model import Analysis, ArmSummary, Comparison, Interval, TaskCell, TrialRecord

__all__ = [
    "analyze",
    "bootstrap_mean_ci",
    "holm",
    "paired_bootstrap_diff",
    "paired_ratio_ci",
    "sign_flip_test",
    "wilson_interval",
]

# Exact enumeration of 2**16 sign patterns is cheap; beyond that, Monte Carlo.
_EXACT_MAX_NONZERO = 16
# Absolute tolerance when comparing permutation statistics, so float noise in summation order
# never excludes the observed pattern (or its mirror image) from the count.
_TIE_TOL = 1e-12
_FEW_TASKS = 5

RngLike = random.Random | int | str | None


def _rng(rng: RngLike) -> random.Random:
    if isinstance(rng, random.Random):
        return rng
    return random.Random(0 if rng is None else rng)


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile (the common "type 7" definition)."""
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    pos = q * (n - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def _percentile_interval(estimate: float, stats: list[float], alpha: float) -> Interval:
    if not stats:
        return Interval(estimate, None, None)
    stats.sort()
    return Interval(estimate, _quantile(stats, alpha / 2), _quantile(stats, 1 - alpha / 2))


def _bootstrap(
    n: int,
    statistic: Callable[[list[int]], float | None],
    estimate: float,
    *,
    n_boot: int,
    alpha: float,
    rng: RngLike,
) -> Interval:
    """Percentile bootstrap over ``n`` resampling units (indices).

    With one unit every resample is identical, so the "interval" would be a point that says
    nothing about uncertainty; bounds are left as None instead.
    """
    if n < 2:
        return Interval(estimate, None, None)
    r = _rng(rng)
    population = range(n)
    stats: list[float] = []
    for _ in range(n_boot):
        value = statistic(r.choices(population, k=n))
        if value is not None:  # undefined resamples (e.g. zero denominator) are skipped
            stats.append(value)
    return _percentile_interval(estimate, stats, alpha)


# --------------------------------------------------------------------------- public helpers


def wilson_interval(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion ``k / n``.

    Preferred over the normal (Wald) interval because it stays inside [0, 1] and behaves well
    at 0 and n successes. With ``n == 0`` nothing is known, so the full range (0, 1) is returned.
    """
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"invalid binomial counts k={k}, n={n}")
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    # Clamp float noise at the boundaries (k == 0 or k == n give exactly 0 or 1 in theory).
    low = 0.0 if k == 0 else max(0.0, center - half)
    high = 1.0 if k == n else min(1.0, center + half)
    return (low, high)


def bootstrap_mean_ci(
    values: Sequence[float],
    *,
    n_boot: int = 10000,
    alpha: float = 0.05,
    rng: RngLike = None,
) -> Interval:
    """Percentile bootstrap CI for the mean of ``values``.

    Empty input gives an all-None interval; a single value gives the estimate with None bounds.
    """
    vals = [float(v) for v in values]
    n = len(vals)
    if n == 0:
        return Interval(None, None, None)
    return _bootstrap(
        n,
        lambda idx: sum(map(vals.__getitem__, idx)) / n,
        fmean(vals),
        n_boot=n_boot,
        alpha=alpha,
        rng=rng,
    )


def paired_bootstrap_diff(
    a: Sequence[float],
    b: Sequence[float],
    *,
    n_boot: int = 10000,
    alpha: float = 0.05,
    rng: RngLike = None,
) -> Interval:
    """Percentile bootstrap CI for ``mean(b - a)``, resampling pairs (tasks) together."""
    if len(a) != len(b):
        raise ValueError("paired samples must have equal length")
    diffs = [float(y) - float(x) for x, y in zip(a, b, strict=True)]
    return bootstrap_mean_ci(diffs, n_boot=n_boot, alpha=alpha, rng=rng)


def paired_ratio_ci(
    a: Sequence[float],
    b: Sequence[float],
    *,
    n_boot: int = 10000,
    alpha: float = 0.05,
    rng: RngLike = None,
) -> Interval:
    """Percentile bootstrap CI for ``mean(b) / mean(a)``, resampling pairs together.

    A ratio of means (not a mean of per-task ratios) keeps cheap tasks from dominating and is
    defined even when some per-task baseline values are zero. If ``mean(a)`` is 0 the ratio is
    undefined and the estimate is None; resamples with a zero denominator are skipped.
    """
    if len(a) != len(b):
        raise ValueError("paired samples must have equal length")
    xa = [float(v) for v in a]
    xb = [float(v) for v in b]
    n = len(xa)
    if n == 0:
        return Interval(None, None, None)
    mean_a = fmean(xa)
    if mean_a == 0:
        return Interval(None, None, None)

    def ratio(idx: list[int]) -> float | None:
        den = sum(map(xa.__getitem__, idx))
        if den == 0:
            return None
        return sum(map(xb.__getitem__, idx)) / den

    return _bootstrap(n, ratio, fmean(xb) / mean_a, n_boot=n_boot, alpha=alpha, rng=rng)


def sign_flip_test(
    diffs: Sequence[float],
    *,
    n_perm: int = 20000,
    rng: RngLike = None,
) -> float:
    """Two-sided paired sign-flip permutation test of mean(diffs) == 0.

    Under the null the two arms are exchangeable within a task, so each per-task difference is
    equally likely to have either sign. The statistic is ``|mean(diffs)|``; zero differences
    flip to themselves and stay in the denominator. Exact enumeration is used when at most 16
    differences are non-zero, otherwise Monte Carlo with the ``(hits + 1) / (n + 1)`` correction
    (which keeps the test valid). All-zero input gives 1.0; empty input gives NaN.
    """
    vals = [float(d) for d in diffs]
    n = len(vals)
    if n == 0:
        return math.nan
    nonzero = [d for d in vals if d != 0]
    if not nonzero:
        return 1.0
    observed = abs(math.fsum(nonzero)) / n
    threshold = observed - _TIE_TOL

    if len(nonzero) <= _EXACT_MAX_NONZERO:
        sums = [0.0]
        for d in nonzero:
            sums = [s + d for s in sums] + [s - d for s in sums]
        hits = sum(1 for s in sums if abs(s) / n >= threshold)
        return hits / len(sums)

    r = _rng(rng)
    hits = 0
    for _ in range(n_perm):
        s = math.fsum(d if r.random() < 0.5 else -d for d in nonzero)
        if abs(s) / n >= threshold:
            hits += 1
    return (hits + 1) / (n_perm + 1)


def holm(pvalues: Sequence[float | None]) -> list[float | None]:
    """Holm step-down adjustment (controls the family-wise error rate).

    None (or NaN) entries are passed through as None and do not count toward the family size.
    Adjusted values are made monotone in the sorted order and capped at 1.
    """
    present = [(p, i) for i, p in enumerate(pvalues) if p is not None and not math.isnan(p)]
    out: list[float | None] = [None] * len(pvalues)
    m = len(present)
    running = 0.0
    for rank, (p, i) in enumerate(sorted(present)):
        running = max(running, min(1.0, (m - rank) * p))
        out[i] = running
    return out


# --------------------------------------------------------------------------- analysis


def _mean_or_none(values: Iterable[float | int | None]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return fmean(vals) if vals else None


def _cluster_mean_ci(
    groups: list[list[float]], *, n_boot: int, alpha: float, rng: RngLike
) -> Interval:
    """Per-trial mean with a CI that resamples whole tasks (clusters) of trials."""
    groups = [g for g in groups if g]
    if not groups:
        return Interval(None, None, None)
    sums = [math.fsum(g) for g in groups]
    counts = [len(g) for g in groups]
    estimate = math.fsum(sums) / sum(counts)
    return _bootstrap(
        len(groups),
        lambda idx: sum(map(sums.__getitem__, idx)) / sum(map(counts.__getitem__, idx)),
        estimate,
        n_boot=n_boot,
        alpha=alpha,
        rng=rng,
    )


def _final_attempts(records: Iterable[TrialRecord]) -> dict[str, TrialRecord]:
    final: dict[str, TrialRecord] = {}
    for rec in records:
        prev = final.get(rec.trial_id)
        if prev is None or rec.attempt >= prev.attempt:
            final[rec.trial_id] = rec
    return final


def _trial_groups(
    by_cell: dict[tuple[str, str], list[TrialRecord]], task_ids: list[str], arm: str, attr: str
) -> list[list[float]]:
    """Per task, the reported values of ``attr`` over the arm's completed trials."""
    return [
        [
            float(getattr(r, attr))
            for r in by_cell[(t, arm)]
            if r.status != "error" and getattr(r, attr) is not None
        ]
        for t in task_ids
    ]


def _pairs(
    per_task: dict[str, dict[str, float]], base: str, arm: str, tasks: list[str]
) -> tuple[list[float], list[float]]:
    """(baseline, arm) per-task values, dropping tasks where either side is missing."""
    both = [t for t in tasks if t in per_task[base] and t in per_task[arm]]
    return [per_task[base][t] for t in both], [per_task[arm][t] for t in both]


def _arm_order(exp_meta: dict, finals: Iterable[TrialRecord]) -> list[str]:
    order: list[str] = []
    arms_cfg = (exp_meta.get("config") or {}).get("arms") or []
    for arm in arms_cfg:
        name = arm.get("name") if isinstance(arm, dict) else None
        if isinstance(name, str) and name not in order:
            order.append(name)
    for rec in finals:
        if rec.arm not in order:
            order.append(rec.arm)
    return order


def _short_list(items: Sequence[str], limit: int = 5) -> str:
    shown = ", ".join(items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def analyze(
    exp_meta: dict,
    records: Iterable[TrialRecord],
    *,
    baseline: str | None = None,
    alpha: float = 0.05,
    seed: int = 0,
    n_boot: int = 10000,
) -> Analysis:
    """Summarise a run: per-arm estimates, paired comparisons against the baseline, caveats.

    Only the final attempt of each trial counts. Trials whose final attempt is an
    infrastructure error are excluded from rates and costs but counted in ``errors``.
    Deterministic for a given ``seed``.
    """
    all_records = list(records)
    finals = sorted(_final_attempts(all_records).values(), key=lambda r: r.trial_id)
    arms = _arm_order(exp_meta, finals)
    base = (
        baseline
        if baseline is not None
        else exp_meta.get("baseline") or (arms[0] if arms else None)
    )
    if base is None or base not in arms:
        raise ValueError(f"unknown baseline arm {base!r}; arms: {', '.join(arms) or '(none)'}")

    # Each statistic gets its own named stream so results do not depend on arm order.
    def rng_for(purpose: str) -> random.Random:
        return random.Random(f"agent-ab:{seed}:{purpose}")

    # (task, arm) -> final records
    by_cell: dict[tuple[str, str], list[TrialRecord]] = {}
    for rec in finals:
        by_cell.setdefault((rec.task, rec.arm), []).append(rec)
    tasks = sorted({t for t, _ in by_cell})

    cells: list[TaskCell] = []
    frac: dict[str, dict[str, float]] = {a: {} for a in arms}  # arm -> task -> pass fraction
    task_cost: dict[str, dict[str, float]] = {a: {} for a in arms}
    task_dur: dict[str, dict[str, float]] = {a: {} for a in arms}
    for task in tasks:
        for arm in arms:
            recs = by_cell.get((task, arm))
            if not recs:
                continue
            done = [r for r in recs if r.status != "error"]
            passes = sum(1 for r in done if r.status == "pass")
            cost = _mean_or_none(r.cost_usd for r in done)
            dur = _mean_or_none(r.duration_s for r in done)
            cells.append(TaskCell(task, arm, len(done), passes, len(recs) - len(done), cost, dur))
            if done:
                frac[arm][task] = passes / len(done)
                if cost is not None:
                    task_cost[arm][task] = cost
                if dur is not None:
                    task_dur[arm][task] = dur

    notes: list[str] = []
    summaries: list[ArmSummary] = []
    for arm in arms:
        recs = [r for r in finals if r.arm == arm]
        done = [r for r in recs if r.status != "error"]
        passes = sum(1 for r in done if r.status == "pass")
        n = len(done)
        task_ids = sorted(frac[arm])
        pass_rate = bootstrap_mean_ci(
            [frac[arm][t] for t in task_ids],
            n_boot=n_boot,
            alpha=alpha,
            rng=rng_for(f"pass_rate:{arm}"),
        )
        if n:
            lo, hi = wilson_interval(passes, n)
            wilson = Interval(passes / n, lo, hi)
        else:
            wilson = Interval(None, None, None)

        costs = [r.cost_usd for r in done if r.cost_usd is not None]
        total_cost = math.fsum(costs) if costs else None
        summaries.append(
            ArmSummary(
                arm=arm,
                trials=n,
                errors=len(recs) - n,
                passes=passes,
                tasks=len(task_ids),
                pass_rate=pass_rate,
                pass_rate_wilson=wilson,
                mean_cost_usd=_cluster_mean_ci(
                    _trial_groups(by_cell, task_ids, arm, "cost_usd"),
                    n_boot=n_boot,
                    alpha=alpha,
                    rng=rng_for(f"cost:{arm}"),
                ),
                total_cost_usd=total_cost,
                mean_duration_s=_cluster_mean_ci(
                    _trial_groups(by_cell, task_ids, arm, "duration_s"),
                    n_boot=n_boot,
                    alpha=alpha,
                    rng=rng_for(f"duration:{arm}"),
                ),
                mean_input_tokens=_mean_or_none(r.input_tokens for r in done),
                mean_output_tokens=_mean_or_none(r.output_tokens for r in done),
                mean_turns=_mean_or_none(r.turns for r in done),
                cost_per_pass_usd=(total_cost / passes)
                if total_cost is not None and passes
                else None,
            )
        )
        if n and not costs:
            notes.append(f"Cost was not reported for arm {arm}; cost figures are unavailable.")
        elif costs and len(costs) < n:
            notes.append(
                f"Cost was reported for only {len(costs)} of {n} completed trials in arm {arm}; "
                "its cost totals are partial."
            )
        if len(task_ids) == 1:
            notes.append(
                f"Arm {arm} completed only one task, so its pass-rate interval is not computed."
            )

    # Paired comparisons against the baseline, over tasks completed in both arms.
    comparisons: list[Comparison] = []
    for arm in arms:
        if arm == base:
            continue
        paired = sorted(set(frac[arm]) & set(frac[base]))
        diffs = [frac[arm][t] - frac[base][t] for t in paired]
        diff_ci = paired_bootstrap_diff(
            [frac[base][t] for t in paired],
            [frac[arm][t] for t in paired],
            n_boot=n_boot,
            alpha=alpha,
            rng=rng_for(f"diff:{arm}"),
        )
        p = sign_flip_test(diffs, rng=rng_for(f"perm:{arm}")) if paired else None

        comparisons.append(
            Comparison(
                arm=arm,
                baseline=base,
                paired_tasks=len(paired),
                pass_rate_diff=diff_ci,
                p_value=p,
                p_value_adjusted=None,
                cost_ratio=paired_ratio_ci(
                    *_pairs(task_cost, base, arm, paired),
                    n_boot=n_boot,
                    alpha=alpha,
                    rng=rng_for(f"cost_ratio:{arm}"),
                ),
                duration_ratio=paired_ratio_ci(
                    *_pairs(task_dur, base, arm, paired),
                    n_boot=n_boot,
                    alpha=alpha,
                    rng=rng_for(f"duration_ratio:{arm}"),
                ),
                tasks_better=sum(1 for d in diffs if d > _TIE_TOL),
                tasks_worse=sum(1 for d in diffs if d < -_TIE_TOL),
                tasks_tied=sum(1 for d in diffs if abs(d) <= _TIE_TOL),
                verdict="insufficient data",
            )
        )
        if len(paired) < 2:
            notes.append(
                f"{arm} vs {base}: {len(paired)} paired task(s); at least 2 are needed to compare."
            )
        elif len(paired) < _FEW_TASKS:
            notes.append(
                f"{arm} vs {base}: only {len(paired)} paired tasks, so intervals are wide."
            )

    for comp, adj in zip(comparisons, holm([c.p_value for c in comparisons]), strict=True):
        comp.p_value_adjusted = adj
        ci = comp.pass_rate_diff
        if comp.paired_tasks < 2:
            comp.verdict = "insufficient data"
        elif adj is not None and adj < alpha and ci.low is not None and ci.low > 0:
            comp.verdict = "better"
        elif adj is not None and adj < alpha and ci.high is not None and ci.high < 0:
            comp.verdict = "worse"
        else:
            # Includes a significant p with a CI touching 0: the two methods disagree at the
            # margin, and the conservative reading is that no difference was detected.
            comp.verdict = "no detectable difference"

    flaky = sorted({c.task for c in cells if 0 < c.passes < c.trials})

    completed = sum(1 for r in finals if r.status != "error")
    errors = len(finals) - completed
    planned = int(exp_meta.get("planned_trials") or 0)
    spent = [r.cost_usd for r in all_records if r.cost_usd is not None]

    if errors:
        notes.insert(
            0,
            f"{_plural(errors, 'trial')} excluded as infrastructure errors "
            "(final attempt failed for reasons outside the configuration under test).",
        )
    if planned and len(finals) < planned:
        notes.append(
            f"The run is incomplete: {len(finals)} of {planned} planned trials finished "
            "(stopped early, for example by the budget or an interruption)."
        )
    one_sided = sorted(t for t in tasks if 0 < sum(1 for a in arms if t in frac[a]) < len(arms))
    if one_sided:
        notes.append(
            f"{_plural(len(one_sided), 'task')} completed in only some arms "
            f"({_short_list(one_sided)}); excluded from comparisons that lack them."
        )
    trial_counts = {c.trials for c in cells if c.trials}
    if len(trial_counts) > 1:
        notes.append(
            f"Completed trials per task and arm range from {min(trial_counts)} to "
            f"{max(trial_counts)}; pass fractions based on fewer trials are noisier."
        )

    return Analysis(
        experiment=str(exp_meta.get("experiment", "")),
        baseline=base,
        alpha=alpha,
        arms=summaries,
        comparisons=comparisons,
        cells=cells,
        flaky_tasks=flaky,
        planned_trials=planned,
        completed_trials=completed,
        error_trials=errors,
        total_cost_usd=math.fsum(spent) if spent else None,
        notes=notes,
    )
