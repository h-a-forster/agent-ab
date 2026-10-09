# Statistics

This page explains how agent-ab turns trial outcomes into pass rates, intervals, p-values
and verdicts, and why it is designed this way.

## The data

An experiment runs every task under every arm, `repeats` times. Each trial ends as `pass`,
`fail` or `error` (an infrastructure error). Only the last attempt of each trial is used.

For each (task, arm) cell, agent-ab computes the **pass fraction**: passes divided by
completed (pass or fail) trials. With 3 repeats a cell's fraction is 0, 1/3, 2/3 or 1.

## Tasks are the unit of replication

Trials of the same task are not independent. Some tasks are easy for every arm, some are
hard for every arm, and repeats of one task share whatever makes it easy or hard. Treating
360 trials over 40 tasks as 360 independent coin flips overstates how much you know: the
evidence is closer to 40 observations than 360.

So every inference in agent-ab treats the **task** as the unit:

- An arm's **pass rate** is the mean, over tasks, of the cell pass fractions. Each task
  weighs the same, however many trials completed.
- Intervals resample tasks, not trials.
- Comparisons pair arms on the same task.

This answers the question you usually care about: "on tasks like these, does arm B solve
more of them than arm A?"

## Arm pass rate and its interval

The interval for an arm's pass rate is a percentile **cluster bootstrap**: draw tasks with
replacement (keeping all of a task's trials together), recompute the mean of the pass
fractions, repeat many times (10,000 by default), and take the 2.5th and 97.5th percentiles
for a 95% interval.

### Why a trial-level Wilson interval is shown but not used

Reports also show a Wilson score interval computed from total passes over total trials. It
treats every trial as independent, so when tasks differ in difficulty it is too narrow. It
is shown for comparison with tools that report trial-level intervals, and because a large
gap between it and the cluster interval tells you task heterogeneity dominates. Verdicts
never use it.

## Comparing an arm with the baseline

Comparisons use only tasks where **both** arms have at least one completed trial (paired
tasks). For each paired task:

```text
d_task = pass_fraction(arm, task) − pass_fraction(baseline, task)
```

- The **pass-rate difference** is the mean of `d_task`, in absolute terms (`0.10` is reported
  as +10 points).
- Its **confidence interval** is a percentile bootstrap over paired tasks.
- **Tasks better / worse / tied** count tasks with `d_task` above, below and equal to zero.

Pairing removes task difficulty from the comparison. A hard task drags both arms down
equally, so it does not widen the interval for the difference.

### The paired sign-flip test

The p-value comes from a two-sided **sign-flip permutation test** on the `d_task` values.
Under the null hypothesis that the arm makes no difference, the labels "arm" and "baseline"
are exchangeable within each task, so each `d_task` is equally likely to have either sign.
The test compares the observed mean difference with the distribution of mean differences
under random sign flips.

- With 16 or fewer non-zero differences, all sign patterns are enumerated (exact test).
- With more, a Monte Carlo sample is used (20,000 by default), with the `(hits + 1) / (n + 1)`
  correction so the p-value is never zero.
- If every difference is zero, p = 1.

The test makes no distributional assumptions beyond exchangeability, and it handles the
discrete values of `d_task` correctly.

### Multiple comparisons: Holm

With several arms, each is compared with the baseline. Running k tests at level `alpha`
raises the chance that at least one is a false positive. agent-ab applies the **Holm**
step-down correction across all comparisons in the report and uses the adjusted p-values for
verdicts. With one comparison the adjusted and raw p-values are equal.

### Verdict rules

| Condition | Verdict |
|---|---|
| fewer than 2 paired tasks | `insufficient data` |
| Holm-adjusted p < `alpha` **and** the CI excludes 0, difference > 0 | `better` |
| Holm-adjusted p < `alpha` **and** the CI excludes 0, difference < 0 | `worse` |
| otherwise | `no detectable difference` |

`alpha` defaults to 0.05; change it with `agent-ab report --alpha`. Requiring both the test
and the interval to agree avoids a verdict when the two methods disagree near the boundary.

### "No detectable difference" is not "no difference"

A non-significant result means the data is compatible with no effect. It is also compatible
with every effect inside the confidence interval. Always read the interval:

- `-1.5 pts (-3.0, +0.2)` with many tasks: any effect is probably small.
- `-7.5 pts (-16.7, +1.7)`: the arm might be clearly worse; the experiment cannot tell.

Reports always show the interval next to the verdict for this reason.

## Cost and time ratios

For each arm and task, agent-ab averages cost (and agent duration) over completed trials.
The **cost ratio** is the mean of these per-task means for the arm divided by the same for
the baseline, over paired tasks. Its interval is a bootstrap over paired tasks. A ratio of
0.8 means the arm cost about 20% less per trial.

If an arm reports no cost (for example the Codex adapter without prices), the ratio is not
computed and a note says so. If the baseline's mean is zero, the ratio has no estimate.

**Cost per pass** is total cost divided by total passes. It combines cost and success into
the number you pay per solved task.

## Infrastructure errors and their bias risk

Attempts that end in an infrastructure error are retried up to `max_retries` times. Trials
whose final attempt is still an error are **excluded** from every statistic, and the report
notes how many.

Exclusion is unbiased only if errors are unrelated to the arm and the task outcome. That is
not guaranteed. For example:

- An arm that produces much longer sessions may hit rate limits more often, and the trials
  it loses may be the hardest ones.
- A larger model may be more likely to be overloaded at peak times.

If error counts differ noticeably between arms, or concentrate on particular tasks, treat
the comparison with suspicion: resume the run to retry (see
[run-directory.md](run-directory.md#resume)), or rerun the affected arms at a quieter time.
The per-arm error counts in the report are there so you can check.

Timeouts are not infrastructure errors. By default (`timeout_is_failure = true`) an agent
timeout is a fail, because running out of time is a legitimate outcome of a configuration.

## Flaky tasks

A task is listed as **flaky** if, within some arm, it both passed and failed across repeats.
Flakiness comes from the agent's own randomness or from a flaky check. The first is
expected; the second is noise you should remove. Run `agent-ab validate --tasks` repeatedly
to rule out the check. See [tasks.md](tasks.md#avoid-flaky-checks).

## Power rule of thumb

How many tasks do you need to detect a given difference? Take the simplest case, one trial
per task per arm. Then `d_task` is -1, 0 or +1. Let `q` be the fraction of tasks that are
discordant (pass in one arm, fail in the other) and `d` the true difference in pass rate.
The variance of `d_task` is

```text
Var(d_task) = q − d²
```

The normal approximation for a two-sided test at level 0.05 with 80% power gives

```text
n ≈ (z₀.₀₂₅ + z₀.₂₀)² × Var(d_task) / d²
  ≈ (1.96 + 0.84)² × (q − d²) / d²
  ≈ 7.84 × (q − d²) / d²
```

| `d` | `q` | `n` (paired tasks) |
|---|---|---|
| 0.20 | 0.30 | about 50 |
| 0.10 | 0.20 | about 150 |
| 0.10 | 0.30 | about 230 |
| 0.05 | 0.20 | about 600 |

Discordance `q` is at least `d`, and in practice usually two to three times larger, because
agents fail some tasks in each arm for reasons unrelated to the change.

Consequences:

- Detecting a 10-point difference needs on the order of a hundred-plus paired tasks.
- With 20-30 tasks, only differences of 25-30 points or more are reliably detectable.
- Repeats turn `d_task` into a difference of fractions and remove some trial-level noise,
  so with 3 repeats the numbers above are somewhat conservative. They do not remove the
  variation between tasks, so they are not a substitute for more tasks.
- Holm correction with several arms raises the bar for each comparison.

A practical approach: run a pilot with the tasks you have, read the interval width, and use
it to decide whether more tasks are worth building.

## Determinism

The analysis is a pure function of the trial records and the analysis seed. Rerunning
`agent-ab report` with the same `--seed` produces the same intervals and p-values. The seed
affects only the Monte Carlo parts (bootstrap and, for more than 16 non-zero differences,
the permutation test); with the default number of resamples, changing it moves interval
endpoints by small amounts.
