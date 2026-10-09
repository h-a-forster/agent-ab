# agent-ab report: claude-haiku-no-tests

baseline control · 10 tasks · 60/60 trials completed · 0 errors · total cost $9.16 · alpha 0.05

## Pass-rate difference vs control

| Arm | Diff | 95% CI (pts) | p | p (Holm) | Verdict | Cost ratio | Time ratio | Paired tasks (better/worse/tied) |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| no-tests | 0.0 pts | [-26.7, +23.3] | 1.00 | 1.00 | no detectable difference | x0.56 [0.42, 0.74] | x0.58 [0.41, 0.86] | 10 (2/1/7) |

## Arms

| Arm | Pass rate | 95% CI | Tasks | Trials | Errors | Cost/trial | Cost/pass | Time/trial | Tokens in/out |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| control (baseline) | 60.0% | 33.3%-86.7% | 10 | 30 | 0 | $0.196 | $0.327 | 2m 05s | 148/12k |
| no-tests | 60.0% | 36.7%-83.3% | 10 | 30 | 0 | $0.109 | $0.182 | 1m 12s | 65/7.9k |

<details><summary>Tasks where arms differ (3 of 10)</summary>

| Task | control | no-tests |
| --- | ---: | ---: |
| dst-daily-schedule | 3/3 | 0/3 |
| semver-precedence | 0/3 | 2/3 |
| csv-quoted-newlines | 0/3 | 1/3 |

</details>

## Flaky tasks

csv-quoted-newlines, dedupe-quadratic, money-decimal-rounding, semver-precedence

## Notes

- no-tests vs control: only 10 paired tasks. Intervals from few tasks tend to be too narrow; verdicts rely on the paired permutation test.

<sub>Pass rate = mean over tasks of each task's pass fraction. 95% CI: bootstrap over tasks. p: paired sign-flip test over tasks, Holm-adjusted across comparisons.</sub>
