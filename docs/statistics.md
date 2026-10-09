# Statistics

How agent-ab turns trial outcomes into pass rates, intervals, p-values and verdicts.

## Data

Each trial ends as `pass`, `fail` or `error` (infrastructure error). Only the last attempt
of a trial counts. For each (task, arm) cell, the **pass fraction** is passes divided by
completed (pass or fail) trials. With 3 repeats it is 0, 1/3, 2/3 or 1.

## Tasks are the unit

Repeats of one task are not independent: some tasks are easy for every arm, some are hard.
360 trials over 40 tasks carry closer to 40 observations' worth of evidence than 360. So
every statistic treats the task as the unit:

- An arm's **pass rate** is the mean of its cell pass fractions. Every task weighs the same.
- Intervals resample tasks, not trials.
- Comparisons pair arms on the same task.

## Arm pass rate

The interval is a percentile **cluster bootstrap**: resample tasks with replacement,
recompute the mean pass fraction, repeat 10,000 times, take the `alpha/2` and `1 - alpha/2`
percentiles.

`analysis.json` also contains a Wilson score interval over all trials
(`pass_rate_wilson`), at the same `alpha`. It treats trials as independent, so it is too
narrow when tasks differ. Reports do not show it and verdicts do not use it.

## Comparing an arm with the baseline

Comparisons use **paired tasks**: tasks with at least one completed trial in both arms. For
each paired task:

```text
d_task = pass_fraction(arm, task) - pass_fraction(baseline, task)
```

- The **difference** is the mean of `d_task`, reported in percentage points.
- Its **CI** is a percentile bootstrap over paired tasks.
- **Better / worse / tied** count tasks with `d_task` above, below and equal to zero.

Pairing removes task difficulty: a hard task lowers both arms equally.

### Sign-flip permutation test

The p-value is a two-sided paired **sign-flip permutation test** on the `d_task` values.
If the arm makes no difference, each `d_task` is equally likely to have either sign. The test
compares the observed mean with the means under random sign flips.

- Up to 16 non-zero differences: all sign patterns are enumerated (exact).
- More: 20,000 random flips, with `(hits + 1) / (n + 1)` so p is never zero.
- All differences zero: p = 1.

The smallest possible p with `n` paired tasks is `2^(1-n)`. With 5 or fewer tasks, p < 0.05
is impossible; the report says so.

### Holm correction

With several arms, each is compared with the baseline. agent-ab applies the Holm step-down
correction across those comparisons and uses the adjusted p for verdicts. With one
comparison, adjusted and raw p are equal.

### Verdicts

| Condition | Verdict |
|---|---|
| fewer than 2 paired tasks | `insufficient data` |
| Holm p < `alpha` and CI entirely above 0 | `better` |
| Holm p < `alpha` and CI entirely below 0 | `worse` |
| otherwise | `no detectable difference` |

`alpha` defaults to 0.05; change it with `agent-ab report --alpha`. Requiring both the test
and the interval avoids a verdict when they disagree at the margin.

"No detectable difference" is not "no difference". The data is compatible with every effect
inside the CI:

- `-1.5 pts [-3.0, +0.2]`: any effect is probably small.
- `-7.5 pts [-16.7, +1.7]`: the arm may be clearly worse; the experiment cannot tell.

### Notes on small experiments

- Fewer than 20 paired tasks: the report notes that intervals from few tasks tend to be too
  narrow (the percentile bootstrap undercovers) and that verdicts rely on the permutation
  test, which is exact.
- Every task has the same difference: the CI has zero width and is not informative.

## Cost and time ratios

For each arm and task, cost and agent duration are averaged over completed trials. The
**cost ratio** is the arm's mean of these per-task values divided by the baseline's, over
paired tasks, with a bootstrap CI. 0.8 means the arm cost about 20% less per trial.

If an arm reports no cost (for example `codex` without prices), the ratio is not computed.
If the baseline cost is mostly zero, a note says the ratio's interval is unreliable.

**Cost per pass** is total cost divided by total passes.

## Infrastructure errors

Trials whose final attempt is an infrastructure error are excluded from every statistic,
and the report counts them. Exclusion is unbiased only if errors are unrelated to the arm
and the outcome. An arm with longer sessions may hit rate limits more often, and lose its
hardest trials. If error counts differ between arms, resume the run to retry them (see
[run-directory.md](run-directory.md#resume)).

Agent timeouts are not infrastructure errors. With `timeout_is_failure = true` (the
default) they are fails.

## Flaky tasks

A task is **flaky** if, within some arm, it both passed and failed across repeats. The
cause is the agent's randomness or a flaky check. Rule out the check by running
`agent-ab validate --tasks` several times.

## How many tasks

Run `agent-ab power` for an estimate by simulation; see [power.md](power.md). The intuition
behind it:

Take one trial per task per arm. Then `d_task` is -1, 0 or +1. If a fraction `q` of tasks
are discordant (pass in one arm, fail in the other) and the true difference is `d`, then
`Var(d_task) = q - d^2`. The normal approximation for 80% power at a two-sided 5% level
gives

```text
n ≈ (1.96 + 0.84)^2 × (q - d^2) / d^2  ≈  7.84 × (q - d^2) / d^2
```

For `d = 0.10` and `q = 0.20` that is about 150 paired tasks; for `d = 0.20` and `q = 0.30`,
about 50. `q` is at least `d` and usually two to three times larger.

Caveats:

- The permutation test is discrete, so at these `n` its power is about 72-77%, not 80%.
  Plan for roughly 20% more tasks.
- Repeats help when the effect is similar across tasks: they average out trial-level noise.
  In simulation, 100 tasks with 3 repeats each reached about 87% power for a 10-point
  difference. They do not help with an effect that varies between tasks, and they cannot
  tell you about tasks you did not include.
- Holm correction with several arms raises the bar for each comparison.

Small suites detect only large effects. Run a pilot, look at the CI width, and decide
whether more tasks are worth building.

## Determinism

The analysis is a pure function of the trial records and the analysis seed (`--seed`,
default 0). The seed affects only the bootstrap and, above 16 non-zero differences, the
permutation test.
