# Power planning

`agent-ab power` estimates how likely an experiment of a given size is to detect a given
improvement in pass rate. Run it before an expensive run to choose the number of tasks and
repeats. Running too few tasks is the most common way to waste a run: the report then says
"no detectable difference" whether or not the arms differ.

```text
agent-ab power [RUN_DIR] [--effect PTS[,PTS...]] [--tasks N[,N...]] [--repeats R[,R...]]
               [--alpha A] [--sims N] [--seed S] [--format text|md|json]
```

| Option | Default | Meaning |
|---|---|---|
| `RUN_DIR` | none | A pilot run. Its baseline arm sets the task difficulty distribution. |
| `--effect` | `10,20` | Improvements to detect, in percentage points (above 0, below 100). |
| `--tasks` | `10,20,50,100,200` | Task counts to simulate (at least 2). |
| `--repeats` | `1,3` | Repeats per task and arm. |
| `--alpha` | `0.05` | Significance level, as in `agent-ab report`. |
| `--sims` | `400` | Simulated experiments per design. |
| `--seed` | `0` | Simulation seed. The same seed gives the same output. |

Bad values exit with code 2 and a one-line error.

## What it simulates

Each design is one combination of effect, task count and repeats. For each design the
command simulates `--sims` experiments with two arms:

1. Draw a baseline pass probability for each task from the difficulty model.
2. Shift every task's logit by one constant. The shift is solved numerically for each
   simulated experiment so that the mean difference across its tasks equals the effect.
3. Draw `repeats` pass/fail outcomes per task in each arm.
4. Apply the rule the reports use for "better": the paired sign-flip p-value is below
   alpha and the paired bootstrap confidence interval lies above 0.

Power is the share of simulated experiments that detect the improvement. `se` is its
Monte Carlo standard error. The output also lists, for each effect, the design with the
fewest total trials that reaches 80% power, and a false-positive check: the detection rate
at effect 0 for the smallest design, which should stay at or below alpha.

## Assumptions

- **Task difficulty.** Without a pilot run, each task's baseline pass probability is drawn
  from Beta(0.7, 0.7): many tasks are nearly always or nearly never solved, some are in
  between.
- **Effect.** The arm changes every task by the same amount on the logit scale. Tasks near
  0% or 100% move little; tasks near 50% move most. Real effects vary by task, and some
  tasks get worse. Such variation lowers power, so read the numbers as optimistic to
  realistic.
- **Headroom.** If the baseline already passes most tasks, a large effect may not fit. Such
  experiments are capped (the arm passes almost every task) and the output says so.
- **Two arms, one comparison.** With more arms, reports adjust p-values for multiple
  comparisons (Holm), which lowers power somewhat.
- **No infrastructure errors.** Errored trials reduce the data a real run has.

Repeats help most under this model because the effect is the same on every task: extra
repeats then remove noise without adding variation between tasks. When effects differ a lot
between tasks, more tasks help more than more repeats.

## Speed shortcuts

These affect only power estimates, never reports.

- The sign-flip p-value is computed exactly by counting. Per-task differences are multiples
  of `1/repeats`, so the null distribution is a convolution of a few binomials. With at most
  16 non-zero differences this equals the report's exact enumeration; above that, reports
  use a Monte Carlo estimate of the same value.
- The bootstrap uses 400 resamples instead of 10,000. It is skipped when p is already too
  large, and when there are at least 30 tasks and p is below alpha / 50, where the interval
  excludes 0 with near certainty.

The defaults take well under a minute on a laptop. Progress lines go to stderr once a run
takes longer than a couple of seconds.

## Example

```text
$ agent-ab power --effect 10 --tasks 50,100,200
Power plan

Simulations: 400 experiments per design, seed 0, alpha 0.05.
Task difficulty: per-task pass probability ~ Beta(0.7, 0.7) (no pilot run).
Effect model: one logit shift for every task, sized so the mean difference equals the
  effect.
Detected: sign-flip p < 0.05 and bootstrap CI above 0 (the report rule).

effect (pts)  tasks  repeats  trials  power  se (pts)
------------  -----  -------  ------  -----  --------
         +10     50        1     100    18%       1.9
         +10     50        3     300    57%       2.5
         +10    100        1     200    34%       2.4
         +10    100        3     600    89%       1.6
         +10    200        1     400    69%       2.3
         +10    200        3    1200   100%       0.4

Smallest design with at least 80% power:
  +10 pts: 100 tasks x 3 repeats (600 trials in total) reaches 89% power.

False positives at effect 0 (50 tasks x 1 repeat): 2.0% (should be at most 5%).
Real effects vary by task, so read these numbers as optimistic to realistic.
se is the Monte Carlo standard error of each power estimate.
```

`trials` counts both arms. With defaults, 10 or 20 tasks almost never detect a 10-point
improvement.

## Using a pilot run

A small pilot run tells you how hard your own tasks are for the baseline. Pass its run
directory:

```text
agent-ab power runs/pilot --effect 10,15
```

The command reads the baseline arm's final attempts, ignoring infrastructure errors, and
computes each task's pass fraction. Fractions from a few repeats are noisy and often exactly
0 or 1, where a logit shift has no effect. So each fraction is shrunk toward the pooled mean
with a Beta prior fitted by the method of moments. Simulated tasks are drawn from these
shrunk probabilities with replacement. The output names the model and the number of pilot
tasks; fewer than 10 tasks prints a warning, because the distribution is then a rough guess.

A pilot whose tasks are mostly always or never solved gives low power: those tasks cannot
show a difference. Replacing them with tasks of middling difficulty is often cheaper than
adding more of them.
