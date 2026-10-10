# agent-ab report: pilot-haiku-5-5

baseline control · 20 tasks · 20/20 trials completed · 0 errors · total cost $0.546 · alpha 0.05

## Pass-rate difference vs control

No comparisons: the analysis has a single arm.

## Arms

| Arm | Pass rate | 95% CI | Tasks | Trials | Errors | Cost/trial | Cost/pass | Time/trial | Tokens in/out |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| control (baseline) | 100.0% | 100.0%-100.0% | 20 | 20 | 0 | $0.0273 | $0.0273 | 2m 19s | 20/28k |

## Agent environment

| Arm | Model | Agent version | Tools | MCP servers | Plugins | Skills |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| control | claude-haiku-5-5 | 2.1.296 | 39 | none | 3 | 21 |

<sub>Pass rate = mean over tasks of each task's pass fraction. 95% CI: bootstrap over tasks. p: paired sign-flip test over tasks, Holm-adjusted across comparisons.</sub>
