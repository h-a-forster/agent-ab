# agent-ab report: haiku-vs-sonnet-5-5

baseline haiku · 50 tasks · 100/100 trials completed · 0 errors · total cost $8.82 · alpha 0.05

## Pass-rate difference vs haiku

| Arm | Diff | 95% CI (pts) | p | p (Holm) | Verdict | Cost ratio | Time ratio | Paired tasks (better/worse/tied) |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| sonnet | +2.0 pts | [-4.0, +10.0] | 1.00 | 1.00 | no detectable difference | x3.58 [2.35, 5.55] | x0.49 [0.39, 0.61] | 50 (2/1/47) |

## Arms

| Arm | Pass rate | 95% CI | Tasks | Trials | Errors | Cost/trial | Cost/pass | Time/trial | Tokens in/out |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| haiku (baseline) | 94.0% | 86.0%-100.0% | 50 | 50 | 0 | $0.0385 | $0.0410 | 2m 02s | 22/26k |
| sonnet | 96.0% | 90.0%-100.0% | 50 | 50 | 0 | $0.138 | $0.144 | 59.8s | 10/5.7k |

## Agent environment

| Arm | Model | Agent version | Tools | MCP servers | Plugins | Skills |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| haiku | claude-haiku-5-5 | 2.1.296 | 39 | none | 3 | 21 |
| sonnet | claude-sonnet-5-5 → claude-haiku-5-5, claude-sonnet-5-5 | 2.1.296 | 39 | none | 3 | 21 |

<details><summary>Tasks where arms differ (3 of 50)</summary>

| Task | haiku | sonnet |
| --- | ---: | ---: |
| data-interval-sets | 0/1 | 1/1 |
| feature-minire | 1/1 | 0/1 |
| text-template-engine | 0/1 | 1/1 |

</details>

## Notes

- Arm sonnet used more than one model: claude-haiku-5-5, claude-sonnet-5-5.

<sub>Pass rate = mean over tasks of each task's pass fraction. 95% CI: bootstrap over tasks. p: paired sign-flip test over tasks, Holm-adjusted across comparisons.</sub>
