# agent-ab report: claude-sonnet-no-tests

baseline control · 10 tasks · 60/60 trials completed · 0 errors · total cost $7.67 · alpha 0.05

## Pass-rate difference vs control

| Arm | Diff | 95% CI (pts) | p | p (Holm) | Verdict | Cost ratio | Time ratio | Paired tasks (better/worse/tied) |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| no-tests | 0.0 pts | [0.0, 0.0] | 1.00 | 1.00 | no detectable difference | x0.79 [0.70, 0.89] | x0.68 [0.60, 0.78] | 10 (0/0/10) |

## Arms

| Arm | Pass rate | 95% CI | Tasks | Trials | Errors | Cost/trial | Cost/pass | Time/trial | Tokens in/out |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| control (baseline) | 100.0% | 100.0%-100.0% | 10 | 30 | 0 | $0.143 | $0.143 | 34.8s | 12/3.4k |
| no-tests | 100.0% | 100.0%-100.0% | 10 | 30 | 0 | $0.113 | $0.113 | 23.7s | 9/2.4k |

## Notes

- no-tests vs control: every paired task has the same difference \(\+0.0 pts\). There is no variation across tasks, so the interval is not informative.

<sub>Pass rate = mean over tasks of each task's pass fraction. 95% CI: bootstrap over tasks. p: paired sign-flip test over tasks, Holm-adjusted across comparisons.</sub>
