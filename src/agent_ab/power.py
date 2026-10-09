"""Power planning: how many tasks and repeats an experiment needs, by simulation.

Each simulated experiment draws per-task baseline pass probabilities from a difficulty model,
shifts every task's logit by one constant so the expected mean difference equals the requested
effect, draws binomial outcomes for both arms, and applies the decision rule the reports use:
a two-sided paired sign-flip p below alpha and a paired bootstrap CI that excludes 0.

Speed. Per-task differences are multiples of ``1/repeats``, so the sign-flip null distribution
is a convolution of a few binomials and the p-value is computed exactly by counting. For at most
16 non-zero differences this equals ``stats.sign_flip_test`` (which enumerates); beyond that,
reports use a Monte Carlo estimate of the same exact value. The bootstrap uses fewer resamples
than reports (400 by default). It is skipped when p already rules out a detection, and also
when there are at least 30 tasks and p < alpha / 50: the sign-flip statistic is never larger
than the bootstrap's t-like ratio, so such a p puts 0 far outside the interval. These
shortcuts affect only power estimates, never reports. Everything is stdlib-only and
deterministic for a given seed.
"""

from __future__ import annotations

import json
import math
import random
import textwrap
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from statistics import fmean, pvariance

from .model import TrialRecord
from .stats import paired_bootstrap_diff

__all__ = [
    "DesignResult",
    "DifficultyModel",
    "PowerOptions",
    "PowerPlan",
    "beta_model",
    "parse_options",
    "pilot_model",
    "render",
    "run_plan",
    "sign_flip_p_counts",
    "simulate_design",
    "solve_shift",
]

DEFAULT_EFFECTS = "10,20"
DEFAULT_TASKS = "10,20,50,100,200"
DEFAULT_REPEATS = "1,3"
DEFAULT_ALPHA = "0.05"
DEFAULT_SIMS = "400"
TARGET_POWER = 0.80
POWER_N_BOOT = 400
FEW_PILOT_TASKS = 10
_P_CLIP = 1e-6  # keeps logits finite for draws at (or within float noise of) 0 or 1
_MAX_SHIFT = 40.0  # a logit shift this large moves any clipped probability to ~1
_MAX_PRIOR_STRENGTH = 1000.0
# With at least this many tasks and a sign-flip p below alpha * factor, the bootstrap CI
# excludes 0 with overwhelming probability, so it is not computed (a pure speed shortcut).
_SKIP_CI_MIN_TASKS = 30
_SKIP_CI_FACTOR = 0.02


# --------------------------------------------------------------------------- options


@dataclass(frozen=True)
class PowerOptions:
    effects: tuple[float, ...]  # percentage points, ascending
    tasks: tuple[int, ...]
    repeats: tuple[int, ...]
    alpha: float
    sims: int
    seed: int


def _split(text: str, flag: str) -> list[str]:
    parts = [p.strip() for p in str(text).split(",")]
    if not parts or any(not p for p in parts):
        raise ValueError(f"{flag}: expected a comma-separated list, got {text!r}")
    return parts


def _int_list(text: str, flag: str, minimum: int) -> tuple[int, ...]:
    out: set[int] = set()
    for part in _split(text, flag):
        try:
            value = int(part)
        except ValueError:
            raise ValueError(f"{flag}: expected whole numbers, got {part!r}") from None
        if value < minimum:
            raise ValueError(f"{flag}: values must be at least {minimum}, got {value}")
        out.add(value)
    return tuple(sorted(out))


def parse_options(
    *,
    effect: str = DEFAULT_EFFECTS,
    tasks: str = DEFAULT_TASKS,
    repeats: str = DEFAULT_REPEATS,
    alpha: str = DEFAULT_ALPHA,
    sims: str = DEFAULT_SIMS,
    seed: str = "0",
) -> PowerOptions:
    """Validate command-line text; raises ``ValueError`` with a one-line message."""
    effects: set[float] = set()
    for part in _split(effect, "--effect"):
        try:
            value = float(part)
        except ValueError:
            raise ValueError(f"--effect: expected numbers of points, got {part!r}") from None
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"--effect: values must be > 0 points, got {part!r}")
        if value >= 100:
            raise ValueError(f"--effect: values must be below 100 points, got {part!r}")
        effects.add(value)
    try:
        a = float(alpha)
    except ValueError:
        raise ValueError(f"--alpha: expected a number, got {alpha!r}") from None
    if not 0 < a < 1:
        raise ValueError(f"--alpha: must be between 0 and 1, got {alpha!r}")
    try:
        n_sims = int(sims)
    except ValueError:
        raise ValueError(f"--sims: expected a whole number, got {sims!r}") from None
    if n_sims < 1:
        raise ValueError(f"--sims: must be at least 1, got {sims!r}")
    try:
        s = int(seed)
    except ValueError:
        raise ValueError(f"--seed: expected a whole number, got {seed!r}") from None
    return PowerOptions(
        effects=tuple(sorted(effects)),
        tasks=_int_list(tasks, "--tasks", 2),
        repeats=_int_list(repeats, "--repeats", 1),
        alpha=a,
        sims=n_sims,
        seed=s,
    )


# --------------------------------------------------------------------------- difficulty models


@dataclass
class DifficultyModel:
    """Where per-task baseline pass probabilities come from."""

    name: str  # "beta" | "pilot"
    description: str
    sample: Callable[[random.Random], float]
    pilot_tasks: int | None = None
    pilot_mean: float | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "pilot_tasks": self.pilot_tasks,
            "pilot_mean": self.pilot_mean,
        }


def _clip(p: float) -> float:
    return min(max(p, _P_CLIP), 1 - _P_CLIP)


def beta_model(a: float = 0.7, b: float = 0.7) -> DifficultyModel:
    """Heterogeneous tasks: per-task pass probability ~ Beta(a, b) (default: U-shaped)."""
    return DifficultyModel(
        name="beta",
        description=f"per-task pass probability ~ Beta({a:g}, {b:g}) (no pilot run)",
        sample=lambda r: _clip(r.betavariate(a, b)),
    )


def pilot_model(meta: dict, records: Iterable[TrialRecord]) -> DifficultyModel:
    """Empirical task difficulty from a pilot run's baseline arm.

    Each task's observed pass fraction is shrunk toward the pooled mean with a Beta prior fitted
    by the method of moments, so no task sits at exactly 0 or 1 (where a logit shift would do
    nothing). Simulated tasks are drawn from these shrunk probabilities with replacement.
    Raises ``ValueError`` when the baseline arm has no completed trial.
    """
    baseline = meta.get("baseline")
    config = meta.get("config") or {}
    planned = {t.get("id") for t in config.get("tasks") or [] if isinstance(t, dict)}
    final: dict[str, TrialRecord] = {}
    for rec in records:
        prev = final.get(rec.trial_id)
        if prev is None or rec.attempt >= prev.attempt:
            final[rec.trial_id] = rec
    counts: dict[str, list[int]] = {}
    for rec in final.values():
        if rec.arm != baseline or rec.status == "error" or (planned and rec.task not in planned):
            continue
        cell = counts.setdefault(rec.task, [0, 0])
        cell[0] += rec.status == "pass"
        cell[1] += 1
    if not counts:
        raise ValueError(f"the pilot run has no completed trials in baseline arm {baseline!r}")

    cells = [counts[t] for t in sorted(counts)]
    fractions = [k / n for k, n in cells]
    m = fmean(fractions)
    v = pvariance(fractions) if len(fractions) > 1 else 0.0
    strength = m * (1 - m) / v - 1 if v > 0 else _MAX_PRIOR_STRENGTH
    strength = min(max(strength, 1.0), _MAX_PRIOR_STRENGTH)
    prior_a = max(m * strength, 0.5)
    prior_b = max((1 - m) * strength, 0.5)
    probs = [_clip((k + prior_a) / (n + prior_a + prior_b)) for k, n in cells]

    n_tasks = len(cells)
    warnings = []
    if n_tasks < FEW_PILOT_TASKS:
        warnings.append(
            f"only {n_tasks} pilot task(s) inform the difficulty model; "
            f"estimates are rough below {FEW_PILOT_TASKS}"
        )
    return DifficultyModel(
        name="pilot",
        description=(
            f"pilot run, baseline arm {baseline}: {n_tasks} task(s), mean pass rate "
            f"{m * 100:.0f}%, shrunk toward the mean with a Beta({prior_a:.2g}, {prior_b:.2g}) "
            "prior"
        ),
        sample=lambda r: r.choice(probs),
        pilot_tasks=n_tasks,
        pilot_mean=m,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- building blocks


def _expit(x: float) -> float:
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    e = math.exp(x)
    return e / (1 + e)


def solve_shift(probs: Sequence[float], effect: float) -> tuple[float, bool]:
    """Logit shift giving ``mean(expit(logit p + shift) - p) == effect``.

    Bisection on a bracket, accelerated by Newton steps that are taken only when they stay
    inside it. Returns ``(shift, capped)``; ``capped`` is True when the effect exceeds the
    headroom ``1 - mean(p)`` and the largest shift was used instead.
    """
    logits = [math.log(p / (1 - p)) for p in probs]
    n = len(logits)
    target = fmean(probs) + effect

    def at(shift: float) -> tuple[float, float]:
        qs = [_expit(x + shift) for x in logits]
        return math.fsum(qs) / n - target, math.fsum(q * (1 - q) for q in qs) / n

    if at(_MAX_SHIFT)[0] <= 0:
        return _MAX_SHIFT, True
    lo, hi = 0.0, _MAX_SHIFT
    x = 4 * effect  # near the root for mid-range probabilities (slope about 1/4)
    for _ in range(60):
        f, slope = at(x)
        if abs(f) < 1e-9:
            return x, False
        if f < 0:
            lo = x
        else:
            hi = x
        step = x - f / slope if slope > 0 else math.nan
        x = step if lo < step < hi else (lo + hi) / 2
        if hi - lo < 1e-9:
            break
    return x, False


_TailCache = dict[tuple[int, ...], dict[int, float]]


def _tail_table(counts: tuple[int, ...]) -> dict[int, float]:
    """P(|S| >= s) for S = sum of k * (random sign) over ``counts[k-1]`` differences of size k."""
    dist = {0: 1.0}
    for k, c in enumerate(counts, start=1):
        if not c:
            continue
        scale = 2.0**-c
        step = [(k * (2 * j - c), math.comb(c, j) * scale) for j in range(c + 1)]
        new: dict[int, float] = {}
        for s, ps in dist.items():
            for v, pv in step:
                new[s + v] = new.get(s + v, 0.0) + ps * pv
        dist = new
    by_abs: dict[int, float] = {}
    for s, p in dist.items():
        by_abs[abs(s)] = by_abs.get(abs(s), 0.0) + p
    tail: dict[int, float] = {}
    running = 0.0
    for s in sorted(by_abs, reverse=True):
        running += by_abs[s]
        tail[s] = min(running, 1.0)
    return tail


def sign_flip_p_counts(
    diffs: Sequence[int], repeats: int, cache: _TailCache | None = None
) -> float:
    """Exact two-sided sign-flip p for integer differences (``passes_b - passes_a`` per task).

    Same statistic and null as ``stats.sign_flip_test`` on ``diffs / repeats``.
    """
    counts = [0] * repeats
    for d in diffs:
        if d:
            counts[abs(d) - 1] += 1
    key = tuple(counts)
    if cache is None:
        cache = {}
    tail = cache.get(key)
    if tail is None:
        tail = cache[key] = _tail_table(key)
    return tail[abs(sum(diffs))]


# --------------------------------------------------------------------------- simulation


@dataclass(frozen=True)
class DesignResult:
    effect: float  # points
    tasks: int
    repeats: int
    power: float
    se: float
    capped: float  # share of simulated experiments where the effect exceeded the headroom

    @property
    def trials(self) -> int:
        return 2 * self.tasks * self.repeats

    def to_dict(self) -> dict:
        return {
            "effect_pts": self.effect,
            "tasks": self.tasks,
            "repeats": self.repeats,
            "trials": self.trials,
            "power": self.power,
            "se": self.se,
            "capped_fraction": self.capped,
        }


def simulate_design(
    model: DifficultyModel,
    effect_pts: float,
    tasks: int,
    repeats: int,
    *,
    alpha: float,
    sims: int,
    seed: int,
    n_boot: int = POWER_N_BOOT,
    cache: _TailCache | None = None,
) -> DesignResult:
    """Detection rate over ``sims`` simulated experiments of one design.

    With ``effect_pts == 0`` a detection in either direction counts (a false positive);
    otherwise only a detection of an improvement counts.
    """
    r = random.Random(f"agent-ab-power:{seed}:{model.name}:{effect_pts!r}:{tasks}:{repeats}")
    cache = {} if cache is None else cache
    effect = effect_pts / 100
    detected = capped = 0
    for _ in range(sims):
        base = [model.sample(r) for _ in range(tasks)]
        if effect > 0:
            shift, was_capped = solve_shift(base, effect)
            capped += was_capped
            arm = [_expit(math.log(p / (1 - p)) + shift) for p in base]
        else:
            arm = base
        ka = [sum(r.random() < p for _ in range(repeats)) for p in base]
        kb = [sum(r.random() < p for _ in range(repeats)) for p in arm]
        diffs = [b - a for a, b in zip(ka, kb, strict=True)]
        p = sign_flip_p_counts(diffs, repeats, cache)
        if p >= alpha:
            continue
        if p < alpha * _SKIP_CI_FACTOR and tasks >= _SKIP_CI_MIN_TASKS:
            # The bootstrap CI cannot plausibly reach 0 here (see the module notes).
            detected += sum(diffs) > 0 or effect == 0
            continue
        ci = paired_bootstrap_diff(
            [k / repeats for k in ka], [k / repeats for k in kb],
            n_boot=n_boot, alpha=alpha, rng=r,
        )
        up = ci.low is not None and ci.low > 0
        down = ci.high is not None and ci.high < 0
        if up or (effect == 0 and down):
            detected += 1
    power = detected / sims
    return DesignResult(
        effect=effect_pts,
        tasks=tasks,
        repeats=repeats,
        power=power,
        se=math.sqrt(power * (1 - power) / sims),
        capped=capped / sims,
    )


@dataclass
class PowerPlan:
    options: PowerOptions
    model: DifficultyModel
    rows: list[DesignResult]
    false_positive: DesignResult | None

    def recommendation(self, effect: float) -> DesignResult | None:
        """Fewest total trials reaching the target power (ties: higher power)."""
        ok = [d for d in self.rows if d.effect == effect and d.power >= TARGET_POWER]
        return min(ok, key=lambda d: (d.trials, -d.power, d.repeats), default=None)

    def notes(self) -> list[str]:
        out = []
        for effect in self.options.effects:
            worst = max((d.capped for d in self.rows if d.effect == effect), default=0.0)
            if worst > 0:
                out.append(
                    f"+{_pts(effect)} pts exceeds the baseline's headroom in up to "
                    f"{worst:.0%} of simulated experiments; there the arm passes almost every task "
                    "and the simulated effect is smaller than requested."
                )
        return out


def run_plan(
    model: DifficultyModel,
    options: PowerOptions,
    *,
    progress: Callable[[int, int, DesignResult], None] | None = None,
) -> PowerPlan:
    """Simulate every (effect, tasks, repeats) design plus a false-positive check at effect 0
    for the smallest design."""
    cache: _TailCache = {}
    designs = [
        (e, n, k) for e in options.effects for n in options.tasks for k in options.repeats
    ]
    total = len(designs) + 1
    rows: list[DesignResult] = []
    for i, (e, n, k) in enumerate(designs, start=1):
        row = simulate_design(
            model, e, n, k, alpha=options.alpha, sims=options.sims, seed=options.seed,
            cache=cache,
        )
        rows.append(row)
        if progress is not None:
            progress(i, total, row)
    fp = simulate_design(
        model, 0.0, options.tasks[0], options.repeats[0],
        alpha=options.alpha, sims=options.sims, seed=options.seed, cache=cache,
    )
    if progress is not None:
        progress(total, total, fp)
    return PowerPlan(options, model, rows, fp)


# --------------------------------------------------------------------------- rendering


def _pts(x: float) -> str:
    return f"{x:g}"


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _n(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _rec_line(plan: PowerPlan, effect: float) -> str:
    best = plan.recommendation(effect)
    if best is None:
        return (
            f"+{_pts(effect)} pts: none of the simulated designs reach "
            f"{_pct(TARGET_POWER)}; try more tasks."
        )
    return (
        f"+{_pts(effect)} pts: {best.tasks} tasks x {_n(best.repeats, 'repeat')} "
        f"({best.trials} trials in total) reaches {_pct(best.power)} power."
    )


def _fp_line(plan: PowerPlan) -> str | None:
    fp = plan.false_positive
    if fp is None:
        return None
    return (
        f"False positives at effect 0 ({fp.tasks} tasks x {_n(fp.repeats, 'repeat')}): "
        f"{fp.power * 100:.1f}% (should be at most {plan.options.alpha * 100:g}%)."
    )


def _header(plan: PowerPlan) -> list[str]:
    o = plan.options
    return [
        f"Simulations: {o.sims} experiments per design, seed {o.seed}, alpha {o.alpha:g}.",
        f"Task difficulty: {plan.model.description}.",
        "Effect model: one logit shift for every task, sized so the mean difference equals "
        "the effect.",
        f"Detected: sign-flip p < {o.alpha:g} and bootstrap CI above 0 (the report rule).",
    ]


def _footer(plan: PowerPlan) -> list[str]:
    fp = _fp_line(plan)
    return [
        *([fp] if fp else []),
        *plan.notes(),
        "Real effects vary by task, so read these numbers as optimistic to realistic.",
        "se is the Monte Carlo standard error of each power estimate.",
    ]


def _row_cells(d: DesignResult) -> list[str]:
    return [
        f"+{_pts(d.effect)}", str(d.tasks), str(d.repeats), str(d.trials),
        _pct(d.power), f"{d.se * 100:.1f}",
    ]


_HEADERS = ["effect (pts)", "tasks", "repeats", "trials", "power", "se (pts)"]
_WIDTH = 90


def render_text(plan: PowerPlan) -> str:
    rows = [_row_cells(d) for d in plan.rows]
    widths = [len(h) for h in _HEADERS]
    for row in rows:
        widths = [max(w, len(c)) for w, c in zip(widths, row, strict=True)]

    def fmt(cells: Sequence[str]) -> str:
        return "  ".join(c.rjust(w) for c, w in zip(cells, widths, strict=True)).rstrip()

    def wrap(text: str, indent: str = "") -> str:
        return textwrap.fill(
            text, _WIDTH, initial_indent=indent, subsequent_indent=indent + "  "
        )

    lines = ["Power plan", "", *(wrap(h) for h in _header(plan)), ""]
    lines += [fmt(_HEADERS), fmt(["-" * w for w in widths]), *(fmt(r) for r in rows)]
    lines += ["", f"Smallest design with at least {_pct(TARGET_POWER)} power:"]
    lines += [wrap(_rec_line(plan, e), "  ") for e in plan.options.effects]
    lines += ["", *(wrap(f) for f in _footer(plan))]
    return "\n".join(lines) + "\n"


def render_markdown(plan: PowerPlan) -> str:
    lines = ["# Power plan", "", *(f"- {h}" for h in _header(plan)), ""]
    lines.append("| " + " | ".join(_HEADERS) + " |")
    lines.append("|" + "---:|" * len(_HEADERS))
    lines += ["| " + " | ".join(_row_cells(d)) + " |" for d in plan.rows]
    lines += ["", f"## Smallest design with at least {_pct(TARGET_POWER)} power", ""]
    lines += [f"- {_rec_line(plan, e)}" for e in plan.options.effects]
    lines += ["", "## Notes", "", *(f"- {f}" for f in _footer(plan))]
    return "\n".join(lines) + "\n"


def render_json(plan: PowerPlan) -> str:
    o = plan.options
    data = {
        "alpha": o.alpha,
        "sims": o.sims,
        "seed": o.seed,
        "target_power": TARGET_POWER,
        "model": plan.model.to_dict(),
        "rows": [d.to_dict() for d in plan.rows],
        "recommendations": [
            {
                "effect_pts": e,
                "design": (lambda b: b.to_dict() if b else None)(plan.recommendation(e)),
            }
            for e in o.effects
        ],
        "false_positive": plan.false_positive.to_dict() if plan.false_positive else None,
        "notes": plan.notes(),
    }
    return json.dumps(data, indent=2) + "\n"


def render(plan: PowerPlan, fmt: str) -> str:
    return {"text": render_text, "md": render_markdown, "json": render_json}[fmt](plan)
