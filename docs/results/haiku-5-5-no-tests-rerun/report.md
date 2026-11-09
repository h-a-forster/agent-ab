# agent-ab report: haiku-5-5-no-tests

baseline control · 50 tasks · 300/300 trials completed · 0 errors · total cost $10.88 · alpha 0.05

## Pass-rate difference vs control

| Arm | Diff | 95% CI (pts) | p | p (Holm) | Verdict | Cost ratio | Time ratio | Paired tasks (better/worse/tied) |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| no-tests | -2.7 pts | [-6.7, +1.3] | 0.36 | 0.36 | no detectable difference | x0.58 [0.50, 0.65] | x0.60 [0.53, 0.67] | 50 (2/5/43) |

## Arms

| Arm | Pass rate | 95% CI | Tasks | Trials | Errors | Cost/trial | Cost/pass | Time/trial | Tokens in/out |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| control (baseline) | 96.7% | 94.0%-99.3% | 50 | 150 | 0 | $0.0459 | $0.0475 | 2m 50s | 24/26k |
| no-tests | 94.0% | 90.0%-98.0% | 50 | 150 | 0 | $0.0266 | $0.0283 | 1m 42s | 13/20k |

## Agent environment

| Arm | Model | Agent version | Tools | MCP servers | Plugins | Skills |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| control | claude-haiku-5-5 | 2.1.308 | 31 | none | 3 | 22 |
| no-tests | claude-haiku-5-5 | 2.1.308 | 31 | none | 3 | 22 |

<details><summary>Tasks where arms differ (7 of 50)</summary>

| Task | control | no-tests |
| --- | ---: | ---: |
| config-validation-errors | 3/3 | 1/3 |
| bughunt-ledger | 3/3 | 2/3 |
| bughunt-mdhtml | 3/3 | 2/3 |
| feature-minire | 2/3 | 3/3 |
| feature-rope-buffer | 3/3 | 2/3 |
| feature-toml-config | 3/3 | 2/3 |
| state-ttl-cache-tags | 2/3 | 3/3 |

</details>

## Flaky tasks

bughunt-ledger, bughunt-mdhtml, config-validation-errors, data-interval-sets, feature-minire, feature-rope-buffer, feature-toml-config, feature-uri-resolve, state-ttl-cache-tags, text-template-engine

<sub>Pass rate = mean over tasks of each task's pass fraction. 95% CI: bootstrap over tasks. p: paired sign-flip test over tasks, Holm-adjusted across comparisons.</sub>
