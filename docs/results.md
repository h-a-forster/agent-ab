# Results

The first experiment, run on 2026-10-09 with the [10 example tasks](../examples/tasks), is a
pilot. It cannot answer its question: it has too few tasks, and Sonnet passes all of them. The
sections after the pilot report the follow-up: [task calibration](#task-calibration-pilots-on-claude-haiku-55),
a [powered experiment](#powered-experiment-no-tests-on-claude-haiku-55) and a
[model comparison](#model-as-the-arm-haiku-55-vs-sonnet-55). These results show what agent-ab
reports for real agents. They are not a benchmark.

## Pilot: Claude Code with and without tests

### Question

Does telling Claude Code not to write or run tests change its pass rate, cost or time?

| Arm | Prompt |
|---|---|
| `control` (baseline) | The task prompt. The agent decides whether to write tests. |
| `no-tests` | The task prompt plus: "Do not write new tests and do not run the test suite. Implement the change directly, then stop." |

The control arm often wrote no tests anyway. An independent audit of the per-trial diffs (not
committed) found test files in 9 of 30 Haiku control trials and 10 of 30 Sonnet control
trials. It found none in the `no-tests` arm. So the arm mostly stops the agent *running* tests,
not writing them.

- 10 tasks x 2 arms x 3 repeats = 60 trials per model, all completed, 0 infrastructure errors.
- Claude Code 2.1.287, `bypassPermissions`, `--setting-sources project`, 4 trials at a time.
- Windows 11, 2026-10-09. Every trial was graded by the task's hidden check.
- Models: the alias `haiku` resolved to `claude-haiku-4-5-20251001` and `sonnet` to
  `claude-sonnet-5-5`. These are different generations, so Haiku-vs-Sonnet differences mix
  size and generation. The IDs come from the run logs; the committed files predate model
  recording.
- Configs: [haiku/experiment.toml](results/haiku/experiment.toml),
  [sonnet/experiment.toml](results/sonnet/experiment.toml). The only differences are the model
  and the spending caps.

### Summary

| Model | Arm | Pass rate | Cost/trial | Cost/pass | Time/trial | Turns/trial |
|---|---|---:|---:|---:|---:|---:|
| Haiku | control | 60.0% | $0.196 | $0.327 | 2m 05s | 19.3 |
| Haiku | no-tests | 60.0% | $0.109 | $0.182 | 1m 12s | 8.5 |
| Sonnet | control | 100.0% | $0.143 | $0.143 | 35s | 8.8 |
| Sonnet | no-tests | 100.0% | $0.113 | $0.113 | 24s | 6.3 |

`no-tests` vs `control`, paired over the 10 tasks (95% intervals):

| Model | Pass-rate diff | p (Holm) | Verdict | Cost ratio | Time ratio |
|---|---:|---:|---|---:|---:|
| Haiku | 0.0 pts [-26.7, +23.3] | 1.00 | no detectable difference | x0.56 [0.42, 0.74] | x0.58 [0.41, 0.86] |
| Sonnet | 0.0 pts (all tasks 3/3) | 1.00 | no detectable difference | x0.79 [0.70, 0.89] | x0.68 [0.60, 0.78] |

Full reports: [Haiku](results/haiku/report.md), [Sonnet](results/sonnet/report.md).

### Findings

1. **Skipping tests cut cost and time for both models.** Haiku cost 44% less per trial and
   Sonnet 21% less. Both cost intervals exclude 1. Haiku's control arm used more than twice
   as many turns (19.3 vs 8.5).
2. **The pass-rate effect is not measured.** Haiku's interval runs from -27 to +23 points, so
   this design cannot rule out a large effect in either direction. The task-level results
   point both ways:

   | Task (Haiku) | control | no-tests |
   |---|---:|---:|
   | dst-daily-schedule | 3/3 | 0/3 |
   | semver-precedence | 0/3 | 2/3 |
   | csv-quoted-newlines | 0/3 | 1/3 |

   The other 7 tasks were tied.
3. **Sonnet saturates this suite.** It passed 60 of 60 trials, so the suite can only show
   cost and time differences between Sonnet and stronger models. Comparing those models needs
   harder tasks.
4. **Across the two runs, Sonnet cost less than Haiku per pass.** Sonnet cost $0.143 per pass
   in its control arm; Haiku cost $0.327. Haiku took more turns and failed more tasks. These
   are separate runs on different model generations, not a paired comparison. To test it, run
   one experiment with one arm per model.

### How many tasks would it take

`agent-ab power docs/results/haiku` uses the Haiku run as a pilot:

- This design (10 tasks x 3 repeats) detects a 20-point difference 21% of the time.
- For +20 points, 25 tasks x 3 repeats (150 trials) reaches 84% power
  (`--effect=20 --tasks 20,25,30 --repeats 1,3`).
- For +10 points, 90 tasks x 3 repeats (540 trials) reaches 84%; 100 x 3 gives 89%
  (`--effect=10 --tasks 80,90,100 --repeats 3`).

An earlier figure of "about 100 tasks x 1 repeat" for +20 points was an artefact of a coarse
task grid in the tool. The model also assumes one homogeneous effect across tasks. Haiku's
data contradicts that: dst-daily-schedule moved -100 points (3/3 to 0/3) and
semver-precedence +67 points (0/3 to 2/3). Treat these sizes as optimistic.

See [power.md](power.md).

### Caveats

- One machine, one CLI version, one day. Results can change with model and CLI updates.
- Cost is what Claude Code reports, at API prices.
- "Tokens in" in the reports counts uncached input only. Most input is cache reads, which are
  in `trials.jsonl` (`cache_read_tokens`).
- Pass rate, cost and time are each tested on their own. There is no joint correction across
  the three outcomes. Holm adjusts only across arms within the pass-rate comparison.
- The Haiku run spent $9.16 of its $10 budget. A re-run may hit the cap and stop early.
- The test-file counts above come from the audit's inspection of diffs that are not committed.
  Transcripts were not otherwise inspected, so whether the `no-tests` agent fully followed the
  instruction is only partly verified.
- The example tasks are small, single-file Python fixes. Effects on larger codebases can
  differ.

## Task calibration (pilots on Claude Haiku 5.5)

The pilot's tasks were too easy for Sonnet. A powered experiment needs a baseline pass rate
of roughly 40-80%, so that a change in either direction can show. We wrote 20 more tasks to
be harder, then ran control-only pilots on Claude Haiku 5.5 (`claude-haiku-5-5`, Claude Code
2.1.296) to calibrate them.

- **Pilot 1** ([pilot-haiku-5-5](results/pilot-haiku-5-5)): the 20 new tasks, control arm,
  1 repeat. It passed 20/20 and cost $0.55.
- **Pilot 2** ([pilot2-haiku-5-5](results/pilot2-haiku-5-5)): 20 harder tasks, plus the 10
  original tasks. The harder tasks are 10 `bughunt-*` (7 seeded bugs each, in codebases of
  about 800-1100 lines) and 10 `feature-*` (intricate specs checked against oracles). It
  passed 26/30: 16/20 of the hard tasks and 10/10 of the original tasks. It cost $1.51.
- Three of the four failures traced to underspecified prompts: `feature-uri-resolve`,
  `feature-sql-select` and `feature-rope-buffer`. We clarified those prompts before the main
  run. `bughunt-textadv` was a genuine miss.

The target baseline of 40-80% was not reached. Haiku 5.5 is near the ceiling of the tasks we
could write with fully specified prompts.

### Sizing

```sh
agent-ab power docs/results/pilot2-haiku-5-5 --effect=-10,-15,-20 --tasks 30,40,50 --repeats 1,2,3
```

- 30 tasks x 3 repeats had 76% power for a 20-point drop.
- 50 tasks x 3 repeats had 97% power for -20 points, 76% for -15 and 48% for -10.

We chose all 50 example tasks x 3 repeats x 2 arms = 300 trials.

## Powered experiment: no-tests on Claude Haiku 5.5

Same question and arms as the pilot, on 50 tasks with 3 repeats. Config:
[experiment.toml](results/haiku-5-5-no-tests/experiment.toml). Report:
[report.md](results/haiku-5-5-no-tests/report.md).

- 300 trials, all completed, 0 errors. Model `claude-haiku-5-5` (recorded per trial), Claude
  Code 2.1.296, 6 trials at a time. Total cost $9.89.

| Arm | Pass rate | 95% CI | Cost/trial | Time/trial |
|---|---:|---:|---:|---:|
| control | 95.3% | 90.0%-99.3% | $0.0439 | 2m 15s |
| no-tests | 92.7% | 86.7%-97.3% | $0.0220 | 1m 27s |

`no-tests` vs `control`, paired over 50 tasks:

- Pass rate: -2.7 pts [-7.3, +1.3], p 0.40. No detectable difference.
- Cost: x0.50 [0.40, 0.70]. Time: x0.64 [0.53, 0.74].
- Per task: 3 better, 6 worse, 41 tied. 10 tasks were flaky.

The interval rules out a drop larger than about 7 points on these tasks. It cannot rule out
a small harm. The task-level losses are small and scattered: `data-interval-sets` went from
3/3 to 1/3, and five tasks lost one repeat each.

### Manipulation check

[manipulation.py](results/manipulation.py) reads each trial's diff and transcript (artifacts
are not committed; `manipulation.jsonl` in each run directory holds the results). The control
arm wrote tests in 127/150 trials and ran them in 150/150. The `no-tests` arm wrote tests in
3/150 and ran them in 0/150. So the instruction worked as intended. In the first pilot,
Haiku 4.5's control arm rarely wrote tests. Haiku 5.5 tests by default.

### Isolation

With `setting_sources = "project"` and `--strict-mcp-config`, the init event still lists 39
tools, 3 plugins and 21 skills, and no MCP servers, in every trial. These come from the cloud
environment that ran the trials (built-in plugins and environment-provided skills). They are
identical across arms, so they do not confound the comparison. They are part of the setup
measured.

## Model as the arm: Haiku 5.5 vs Sonnet 5.5

The pilot found Sonnet cheaper per pass, but it compared separate runs of different
generations (Haiku 4.5 and Sonnet 5.5). Here the model is the arm: 50 tasks, 1 repeat, control
prompt, 4 trials at a time. Config:
[experiment.toml](results/haiku-vs-sonnet-5-5/experiment.toml). Report:
[report.md](results/haiku-vs-sonnet-5-5/report.md).

| Arm | Pass rate | Cost/trial | Cost/pass | Time/trial |
|---|---:|---:|---:|---:|
| haiku (baseline) | 94.0% | $0.0385 | $0.041 | 2m 02s |
| sonnet | 96.0% | $0.138 | $0.144 | 59.8s |

Sonnet vs Haiku, paired over 50 tasks:

- Pass rate: +2.0 pts [-4.0, +10.0], p 1.00. No detectable difference.
- Cost: x3.58 [2.35, 5.55] per trial. Time: x0.49 [0.39, 0.61].
- Total cost $8.82.

This reverses the pilot's "Sonnet cheaper per pass" (Finding 4 above). Within one generation
and paired by task, Sonnet costs about 3.6 times as much per trial for no detectable
pass-rate gain on these tasks. It finishes in about half the time.

Every Sonnet trial also called `claude-haiku-5-5`, which is Claude Code's helper model. That
accounts for $0.012 of the Sonnet arm's $6.90. Manipulation data: Haiku wrote tests in 45/50
trials and Sonnet in 6/50. Both ran tests in 50/50.

Total agent spend for all the new runs was $20.77 (pilot 1 $0.55, pilot 2 $1.51, main $9.89,
model $8.82), inside the USD 60 cap.

## Limitations of the new runs

- An AI model (Claude Sonnet) wrote the 40 new tasks. Reference solutions checked them. For
  `feature-md-emphasis` we also checked agreement with markdown-it-py.
- Ceiling effects limit what pass rates can show. Both runs are above 90%.
- Task difficulty was calibrated on pilots, and three prompts changed between pilot 2 and
  the main run.
- The model experiment has one repeat per task.
- Time ratios depend on concurrency: 6 trials at a time in the main run and 4 in the model
  run. The arms of a task now run side by side, and each trial record stores its concurrency.
- Costs are the CLI's list-price estimates.
- There is no joint correction across pass rate, cost and time.
- One CLI version (2.1.296). Python tasks only.

## Files

Each of [results/haiku](results/haiku) and [results/sonnet](results/sonnet) contains:

- `experiment.toml`: the configuration.
- `run.json`, `trials.jsonl`: the run record, one line per trial. Per-trial artifacts are not
  included. The committed `run.json` files were stripped of absolute paths by hand. agent-ab
  now writes paths relative to the run directory, so new runs need no editing.
- `report.md`, `report.html`, `analysis.json`: the reports agent-ab wrote.

The new runs live in these directories, each with the same files plus `manipulation.jsonl`
(one line per trial: did it write or run tests):

- [pilot-haiku-5-5](results/pilot-haiku-5-5): pilot 1.
- [pilot2-haiku-5-5](results/pilot2-haiku-5-5): pilot 2.
- [haiku-5-5-no-tests](results/haiku-5-5-no-tests): the powered no-tests experiment.
- [haiku-vs-sonnet-5-5](results/haiku-vs-sonnet-5-5): the model experiment.

Their `run.json` files were written by the new code with relative paths, with no hand
editing. [manipulation.py](results/manipulation.py) produces `manipulation.jsonl`:
`python docs/results/manipulation.py RUN_DIR --out FILE.jsonl`.

Re-analyse without running anything:

```sh
agent-ab report docs/results/haiku
agent-ab power docs/results/haiku
```

Re-run (costs money; read [Safety](../README.md#safety) first). The Haiku run cost $9.16 and
the Sonnet run $7.67:

```sh
agent-ab run docs/results/haiku/experiment.toml
```
