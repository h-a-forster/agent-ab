# Results

The first experiment, run on 2026-10-09 with the [10 example tasks](../examples/tasks), is a
pilot. It cannot answer its question: it has too few tasks, and Sonnet passes all of them. A
powered follow-up is reported after the pilot. These results show what agent-ab reports for
real agents. They are not a benchmark.

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

<!-- powered experiment goes here -->

## Files

Each of [results/haiku](results/haiku) and [results/sonnet](results/sonnet) contains:

- `experiment.toml`: the configuration.
- `run.json`, `trials.jsonl`: the run record, one line per trial. Per-trial artifacts are not
  included. The committed `run.json` files were stripped of absolute paths by hand. agent-ab
  now writes paths relative to the run directory, so new runs need no editing.
- `report.md`, `report.html`, `analysis.json`: the reports agent-ab wrote.

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
