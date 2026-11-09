# agent-ab 0.2.0 (unreleased)

Everything after v0.1.1. The version number is a proposal: trial isolation changes how
`claude-code` authenticates by default.

## Trial isolation for `claude-code`

Each trial now runs with an empty config directory, an allow-listed environment and a workspace
outside the home directory, and agent-ab refuses to start if a parent of the workspace holds
files Claude Code would load. See [adapters.md](adapters.md#isolation) and the "Unreleased"
section of [CHANGELOG.md](../CHANGELOG.md).

**Action needed:** a saved login no longer works by default. Set `ANTHROPIC_API_KEY` or
`CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`), or set `isolation = false`.

## Since that entry

- The pre-run check also refuses `.claude/skills`, `.claude/agents` and `.claude/commands` in the
  parents of the workspace root: Claude Code 2.1.308 loads them from there with
  `--setting-sources project`.
- Claude Platform on AWS and the Amazon Bedrock Mantle endpoint work with isolation:
  `CLAUDE_CODE_USE_ANTHROPIC_AWS`, `CLAUDE_CODE_USE_MANTLE` and `ANTHROPIC_AWS_*` pass the
  allow-list and count as credentials.
- The default workspace root falls back to the system temp directory when the root of the home
  drive is not writable. Before, every adapter failed for an unprivileged POSIX user whose
  `TMPDIR` lies inside the home directory.
- An isolation breach is no longer retried, and three in a row with no graded trial between
  them stop the run: `agent-ab run` exits 1 with the reason, already finished trials stay, and
  `--resume` after fixing the leak runs the breached trials again. Before, a leak on the machine
  paid for every attempt of every trial until the budget ran out, all excluded. Trial records
  gain an `isolation_breach` field.
- Machine failures after the agent ran are infrastructure errors, unchecked leaks are recorded as
  unverified, a run directory takes one session at a time, forced and mixed resumes are recorded
  and need `--force`, breached trials stay open, exhausted errors can be reopened with
  `--retry-errors`, and an outage stops the run. See the "Unreleased" section of
  [CHANGELOG.md](../CHANGELOG.md). **Action needed:** resuming a run from 0.1.1 needs `--force`.
- CI actions are pinned to commit SHAs.
- Docs: the route by which the re-run loaded the user-level `CLAUDE.md` is confirmed, the limits
  of the leak check and managed settings are stated, and the plugins and skills in the init
  event are no longer attributed to the cloud environment.
