# agent-ab report: pilot2-haiku-5-5

baseline control · 30 tasks · 30/30 trials completed · 0 errors · total cost $1.51 · alpha 0.05

## Pass-rate difference vs control

No comparisons: the analysis has a single arm.

## Arms

| Arm | Pass rate | 95% CI | Tasks | Trials | Errors | Cost/trial | Cost/pass | Time/trial | Tokens in/out |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| control (baseline) | 86.7% | 73.3%-96.7% | 30 | 30 | 0 | $0.0502 | $0.0579 | 2m 27s | 21/23k |

## Agent environment

| Arm | Model | Agent version | Tools | MCP servers | Plugins | Skills |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| control | claude-haiku-5-5 | 2.1.296 | 39 | none | 3 | 21 |

<sub>Pass rate = mean over tasks of each task's pass fraction. 95% CI: bootstrap over tasks. p: paired sign-flip test over tasks, Holm-adjusted across comparisons.</sub>
