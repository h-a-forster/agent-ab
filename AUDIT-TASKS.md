# Audit tasks (2026-10-10) — delete this file in the final commit

An independent audit confirmed the stats code (sign-flip, Holm, bootstrap, paired ratio of means) and
that the committed reports reproduce byte-for-byte; 730 tests pass. Below are the soundness gaps, doc
problems and upgrades it found, in priority order.

## A. Harness soundness (code)

1. **Check gaming.** Grading runs `python -m unittest` inside the workspace the agent edited
   (runner.py ~367-371, workspace.py install_checks), so a workspace `unittest/` package shadows the
   stdlib. A `unittest/__main__.py` that exits 0 made a failing check pass. Harden it: run checks with
   `python -I` (or `-P`), or in a clean copy with only the agent's source diff applied. Add a regression
   test using that exploit, and document the residual risk.
2. **Model and CLI version are not recorded.**
   - The CLI's JSON has `modelUsage`, but claude_code.py parse_result_text ignores it. Record the model
     IDs actually used and the CLI version for each trial, in trials.jsonl and run.json, and show them in
     the report.
   - The committed example shows the alias "haiku" resolved to claude-haiku-4-5-20251001 and "sonnet"
     to claude-sonnet-5-5. These are different generations, so state them in docs/results.md.
3. **Absolute paths.**
   - run.json writes paths outside the experiment dir as absolute paths (config.py ~293-297, ~719-727),
     which leaks the home directory and username.
   - The fingerprint hashes those paths (config.py ~771), so it only matches at one clone location.
   - Write paths relative to the run dir (or redact home), and keep absolute paths out of the
     fingerprint.
   - The committed docs/results run.json files were stripped by hand: disclose that in results.md.
4. **power command:**
   - Allow negative effects (power.py ~112 requires > 0), so it can plan "does X hurt?".
   - When the baseline has no headroom (pass rate 100%), say so instead of "try more tasks".
   - Run the false-positive check at a non-degenerate design (10x1 gives 0% just from discreteness).
5. **Isolation is claimed, not verified.** `setting_sources = "project"` isn't documented to exclude
   user MCP servers, connectors, memory or the user CLAUDE.md.
   - Add an option (default on for claude-code) that captures the init event via stream-json (tools,
     MCP servers, model) into the trial record, and pass `--strict-mcp-config`.
   - Check the current CLI flags with `claude --help` before using them.
6. **Arm scheduling:** interleave the arms per task and record concurrency, so cost and time ratios
   aren't confounded by cache warmth or load drift.

## B. Docs (docs/results.md, README)

7. The "80% power for 20 points needs about 100 tasks x 1" claim is an artefact of the coarse grid.
   With a finer grid the tool gives about 25 tasks x 3 repeats (150 trials) at 84%. The +10 claim holds
   (90x3 gives 84%). Fix it, and add that the power model assumes a homogeneous effect, which Haiku's
   data contradicts (dst-daily-schedule -100 pts, semver-precedence +67 pts).
8. Reframe "with and without tests". Control wrote test files in only 9/30 (Haiku) and 10/30 (Sonnet)
   trials, and no-tests wrote none, so the arm mostly suppresses *running* tests. Report this.
9. Also add:
   - the Haiku spend ($9.16 of the $10 budget, so a re-run may hit the cap);
   - that pass rate, cost and time are tested without a joint correction;
   - the model IDs.

## C. CI

10. Bump actions/checkout to v7, astral-sh/setup-uv to v10.3.0 (pinned exact; no floating tags from
    v8), and upload-artifact to v7. The CI log currently warns that Node 20 is deprecated.

## D. New experiment (agent runs; this is what the cloud credits are for)

The example can't answer its own question: n is too small, and Sonnet saturates the 10 tasks.

11. Write 20 new tasks in examples/tasks/, in the same format, that `validate --tasks` accepts. They
    must be harder (multi-file changes, edge cases), so that a pilot shows a baseline pass rate of
    roughly 40-80% on Haiku 5.5. Pilot: 1 repeat, control arm only.
12. Run a new committed experiment (docs/results/<name>/ with experiment.toml): about 30 tasks x 3
    repeats x 2 arms (control vs no-tests) on an explicit model ID, claude-haiku-5-5. Size it with the
    fixed power tool first. Use the new model-recording and isolation capture. Hard cap: USD 60 of total
    agent spend across all runs in this section (set budget_usd and per-trial max_budget_usd).
13. If budget remains, run one paired experiment with the model as the arm (claude-haiku-5-5 vs
    claude-sonnet-5-5, same tasks, control prompt), to test the old Finding 4 ("Sonnet cheaper per
    pass") properly.
14. Write up the results honestly in docs/results.md: keep the old example as a pilot, and add the new
    findings with CIs, power and limitations. Strip or relativise paths with the new code, not by hand.

## E. Research framing (docs, do last, after new results are in)

The repo will be linked from an AI-evaluation company site as research. In README.md, right after the
intro, add `## Findings`: 3-5 bullets, each one plain-language insight plus the numbers behind it,
linked to the exact results section. Use the final, corrected numbers (including new runs) and keep
the caveats. Before the limitations section, add `## Open questions`: 4-6 concrete research questions
the data raises, each with a pointer to the files or scripts to start from. Keep the voice concise and
plain, with no hype.

## Done-check

pytest, ruff check and ruff format --check pass; `agent-ab report` on each committed results dir
reproduces the committed report; every number in docs matches.
