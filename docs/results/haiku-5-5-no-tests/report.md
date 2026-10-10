# agent-ab report: haiku-5-5-no-tests

baseline control · 50 tasks · 300/300 trials completed · 0 errors · total cost $9.89 · alpha 0.05

## Pass-rate difference vs control

| Arm | Diff | 95% CI (pts) | p | p (Holm) | Verdict | Cost ratio | Time ratio | Paired tasks (better/worse/tied) |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| no-tests | -2.7 pts | [-7.3, +1.3] | 0.40 | 0.40 | no detectable difference | x0.50 [0.40, 0.70] | x0.64 [0.53, 0.74] | 50 (3/6/41) |

## Arms

| Arm | Pass rate | 95% CI | Tasks | Trials | Errors | Cost/trial | Cost/pass | Time/trial | Tokens in/out |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| control (baseline) | 95.3% | 90.0%-99.3% | 50 | 150 | 0 | $0.0439 | $0.0461 | 2m 15s | 22/26k |
| no-tests | 92.7% | 86.7%-97.3% | 50 | 150 | 0 | $0.0220 | $0.0237 | 1m 27s | 12/20k |

## Agent environment

| Arm | Model | Agent version | Tools | MCP servers | Plugins | Skills |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| control | claude-haiku-5-5 | 2.1.296 | 39 | none | 3 | 21 |
| no-tests | claude-haiku-5-5 | 2.1.296 | 39 | none | 3 | 21 |

<details><summary>Tasks where arms differ (9 of 50)</summary>

| Task | control | no-tests |
| --- | ---: | ---: |
| data-interval-sets | 3/3 | 1/3 |
| api-config-layers | 2/3 | 3/3 |
| bughunt-ratelimit | 3/3 | 2/3 |
| bughunt-textadv | 2/3 | 3/3 |
| config-validation-errors | 3/3 | 2/3 |
| feature-decimal-context | 2/3 | 3/3 |
| feature-sql-select | 3/3 | 2/3 |
| feature-toml-config | 3/3 | 2/3 |
| text-unified-patch | 3/3 | 2/3 |

</details>

## Flaky tasks

api-config-layers, bughunt-ratelimit, bughunt-textadv, config-validation-errors, data-interval-sets, feature-decimal-context, feature-sql-select, feature-toml-config, text-template-engine, text-unified-patch

<sub>Pass rate = mean over tasks of each task's pass fraction. 95% CI: bootstrap over tasks. p: paired sign-flip test over tasks, Holm-adjusted across comparisons.</sub>
