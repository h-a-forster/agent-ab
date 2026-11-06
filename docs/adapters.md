# Adapters

An adapter turns an arm's agent settings into a process and reads back what the agent spent.
Set it with `adapter = "..."` in `[agent]` or `[arms.agent]`.

| Adapter | Agent | Cost |
|---|---|---|
| [`claude-code`](#claude-code) | Claude Code CLI (`claude -p`) | reported by the CLI |
| [`codex`](#codex) | Codex CLI (`codex exec`) | only if you set token prices |
| [`command`](#command) | any command line | via `usage.json` |
| [`mock`](#mock) | built-in fake agent, offline | simulated |

Every adapter:

- runs the agent with the workspace as its working directory;
- adds `env` to the inherited environment (for `claude-code` with `isolation`, an allow-listed
  part of it) and appends `args` after its own arguments;
- validates `[agent.options]` when the config loads (unknown keys are errors);
- checks that the executable exists before the run starts.

Agent output is saved as `agent.stdout` and `agent.stderr` in the attempt directory.

## Infrastructure errors

An infrastructure error is a failure unrelated to the configuration under test. It is
retried up to `max_retries` times; if it persists, the trial is excluded from statistics and
counted in the report. Two kinds:

- failures before the agent starts: workspace creation, `setup`, or launching the agent;
- problems the adapter reports: authentication, rate limits, provider outages, an unusable
  model, or (Codex) a sandbox that cannot run commands.

An [isolation breach](#isolation) is the exception: it is not retried, and three in a row stop
the run.

Everything else is the agent's outcome. Exiting non-zero, giving up, running out of turns or
budget, or breaking the workspace so grading fails (deleting `.git`, replacing check paths
with links) is a `fail`.

After every trial, leftover agent processes are killed: through a job object on Windows,
through the process group on Linux and macOS.

## Windows batch-file shims

npm installs `claude` and `codex` on Windows as `.cmd` files. `cmd.exe` re-parses the
arguments of `.cmd` and `.bat` files, so an argument could run commands or expand
`%variables%`. agent-ab therefore rejects any argument containing `& | < > ^ % ! "` or a
newline when the executable is a batch file. The prompt is sent on stdin and is not
affected.

If your `model`, `args` or options need those characters, point `executable` at the native
binary instead of the shim, or avoid the characters.

## claude-code

Runs Claude Code in print mode. The prompt goes on stdin. By default the output is
`stream-json`, which includes the session's init event; its last line is the same result
object that `--output-format json` prints.

```text
claude -p --output-format stream-json --verbose --no-session-persistence
       --permission-mode <mode>
       [--model M] [--effort E] [--max-budget-usd X] [--max-turns N]
       [--safe-mode] [--bare] [--setting-sources S] [--strict-mcp-config]
       [--append-system-prompt-file <attempt dir>/append_system_prompt.md]
       <args...>
```

| Key | Where | Default | Meaning |
|---|---|---|---|
| `model` | `[agent]` | CLI default | `--model`. |
| `effort` | `[agent]` | CLI default | `--effort`: `low`, `medium`, `high`, `xhigh` or `max`. |
| `executable` | options | `"claude"` | Name or path of the CLI. |
| `permission_mode` | options | `"bypassPermissions"` | `--permission-mode`. One of `acceptEdits`, `auto`, `bypassPermissions`, `dontAsk`, `manual`, `plan`. |
| `max_budget_usd` | options | none | `--max-budget-usd`: per-trial spend cap. |
| `max_turns` | options | none | `--max-turns`. |
| `safe_mode` | options | `false` | `--safe-mode`: start with customizations disabled. |
| `bare` | options | `false` | `--bare`: minimal mode. Changes how the CLI authenticates; see its help. |
| `setting_sources` | options | none | `--setting-sources`: comma-separated `user`, `project`, `local`. |
| `append_system_prompt` | options | none | Text written to a file and passed with `--append-system-prompt-file`. |
| `capture_init` | options | `true` | Use `--output-format stream-json --verbose` and record the init event (see below). With `false` the CLI runs with `--output-format json` and no init data is recorded. |
| `strict_mcp_config` | options | `true` | `--strict-mcp-config`: use only MCP servers named by `--mcp-config`. agent-ab passes none, so no MCP server (not even your own) is loaded unless you add `--mcp-config` through `args`. |
| `isolation` | options | `true` | Empty config directory and allow-listed environment per trial, plus a leak check; see [Isolation](#isolation). Needs `capture_init`. |
| `pass_env` | options | `[]` | Names of further environment variables to pass to an isolated agent. |

agent-ab records cost (`total_cost_usd`), turns, tokens (including cache reads and writes)
and the final message. Hitting `max_turns` or `max_budget_usd` is a fail. API statuses 401,
403, 404, 408, 429 and 5xx are infrastructure errors.

What is recorded about the agent itself:

- `models`: the model IDs the CLI reports having used (the keys of `modelUsage` in the result),
  sorted. Aliases such as `haiku` resolve to a dated ID, so this is the model actually run.
- `agent_version`: the CLI version. agent-ab runs `<executable> --version` once per arm at the
  start of a run (stored in `run.json` as `agent_versions`) and, when the init event is
  captured, prefers the version the CLI reports during the trial. A failed probe leaves it
  unknown.
- `agent_init`: a compact summary of the init event: `model`, `claude_code_version`,
  `permission_mode`, `api_key_source` and the names of `tools`, `mcp_servers` (with status),
  `plugins`, `skills` and `agents`, plus `config_leaks` (see [Isolation](#isolation)).
- `prompt_sha256` and `instructions_sha256`: hashes of the exact prompt and of the instruction
  files (`CLAUDE.md`, `CLAUDE.local.md`, `.claude/CLAUDE.md` and `AGENTS.md` at the workspace
  root, and `append_system_prompt.md` when set), so two runs can be checked for identical
  copies of those files. Recorded for every adapter; see
  [run-directory.md](run-directory.md#trialsjsonl). Other workspace files (`.claude/rules/`,
  skills, settings, `CLAUDE.md` in subdirectories, `AGENTS.override.md`) and instruction files
  outside the workspace are not hashed: Claude Code can also load user memory
  (`~/.claude/CLAUDE.md`), `CLAUDE.md` files in parent directories, rules and settings.
  `setting_sources = "project"` did not keep user memory out in one of our runs (see
  [Isolation](#isolation)), so equal hashes mean identical instructions only when nothing
  outside the workspace was loaded.
- `init.json` in the attempt directory: the full init event, without `cwd`, `session_id`,
  `uuid`, `scratchpad_path`, `messaging_socket_path`, `startup_timing` and any value that is
  an absolute path. The event is read from the start of the output, so a long transcript does
  not hide it.

The report lists the models, versions and, when init data exists, the number of tools, MCP
servers and plugins per arm, and notes arms that used more than one model, a model other than
the one requested, or a different tool, MCP or plugin set (a confound unless that difference
is what you are testing). Runs without this data produce the same report as before.

To compare a customised setup with a stock one, use an arm with `safe_mode = true` (or
`bare = true`). `strict_mcp_config` keeps your own MCP servers out, and the recorded init
summary lets you check part of what was actually loaded: compare `tools`, `mcp_servers`,
`plugins` and `skills` across arms.

```toml
[agent]
adapter = "claude-code"
model = "sonnet"
effort = "medium"

[agent.options]
setting_sources = "project"
max_turns = 60
max_budget_usd = 2.0

[[arms]]
name = "medium"

[[arms]]
name = "high"
[arms.agent]
effort = "high"
```

### Isolation

Claude Code reads configuration from outside the workspace: its config directory (`~/.claude`,
or `CLAUDE_CONFIG_DIR`) holds user settings, user memory (`CLAUDE.md`, `rules/`), auto memory,
plugins, skills and the saved login; from every parent of its working directory it loads
`CLAUDE.md` files and the `.claude` memory, rules, skills, agents and commands there, whatever
`setting_sources` says; and it inherits the environment. In the
[no-tests re-run](results.md#re-run-with-the-current-grader), made before isolation existed
and with `setting_sources = "project"`, the agents still followed the machine owner's
user-level `CLAUDE.md`, reached that way because the workspaces sat under the home directory,
and used a bash shim set through `CLAUDE_CODE_GIT_BASH_PATH`.

With `isolation = true` (the default) each trial gets:

- **An empty config directory.** `CLAUDE_CONFIG_DIR` points at a fresh directory beside the
  workspace (`<workspace>.claude-config`, outside what the agent edits), removed when the
  agent exits. Your settings, memory, hooks, plugins, skills and saved login stay out.
- **An allow-listed environment.** Operating-system basics (`PATH`, `HOME`, `USERPROFILE`,
  `TEMP`, locale), proxy and certificate settings, and API credentials and provider settings
  (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `CLAUDE_CODE_OAUTH_TOKEN`,
  `CLAUDE_CODE_USE_BEDROCK`, `AWS_*` and similar) pass; everything else is dropped. That
  includes `CLAUDE_CODE_GIT_BASH_PATH`, `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT` and the other
  variables a parent Claude Code session sets, `CLAUDE_CONFIG_DIR`, `ANTHROPIC_MODEL`,
  `PYTHONHOME`, `PYTHONPATH` and `VIRTUAL_ENV` (whose `bin` or `Scripts` directory is also
  taken off `PATH`, so the agent's `python` is not agent-ab's). Checks still run `{python}` as
  agent-ab's own interpreter, so a task that tells the agent to run `python` can reach a
  different Python from the grader's, or none if `PATH` has no other. `pass_env` adds names, and
  `env` applies on top. The full list is `_ENV_ALLOW` in `src/agent_ab/adapters/claude_code.py`.
  On Windows Claude Code finds Git Bash by itself; if it cannot, pass
  `CLAUDE_CODE_GIT_BASH_PATH` on purpose with `pass_env`.
- **Workspaces outside your home directory.** By default workspaces go to the system temp
  directory, or to `agent-ab-workspaces` at the root of the home drive when the temp directory
  is inside the home directory, as on Windows ([`workspace_root`](configuration.md)). Before
  anything runs, agent-ab refuses to start if `CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`,
  `.claude/CLAUDE.md`, `.claude/rules`, `.claude/skills`, `.claude/agents` or
  `.claude/commands` exists in the workspace root or any of its parents.
- **A leak check.** In the raw init event (before it is scrubbed), every path under
  `memory_paths`, and every path naming a `CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md` or
  `.claude/rules` file, must lie inside the workspace or its config directory. Anything else is
  recorded in `agent_init.config_leaks`, reduced to the key and the last path component (for
  example `memory_paths.auto: ~/.../memory`), and makes the attempt an infrastructure error
  excluded from the statistics. A leak comes from the machine, so it is not retried, and three
  breaches in a row with no graded trial between them stop the run: no new trials start, agents
  already running finish and are recorded, and `agent-ab run` exits 1. Finished trials are kept.
  Fix the leak and resume: breached trials run again, whatever `max_retries` says, and a breach
  that recurs stops the run again. The report notes arms with leaks. The init event does not list every file Claude Code loads (2.1.308 listed only the
  auto-memory directory, and `config_leaks` stayed empty with a parent directory's
  `.claude/CLAUDE.md` loaded), so the check catches a foreign config directory but cannot
  prove that nothing else was loaded; the three measures above are what keep user files out.

An empty config directory has no saved login, so an isolated agent authenticates from the
environment. agent-ab refuses to start unless `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
`CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_PROFILE` or one of `CLAUDE_CODE_USE_BEDROCK`,
`CLAUDE_CODE_USE_VERTEX`, `CLAUDE_CODE_USE_FOUNDRY`, `CLAUDE_CODE_USE_MANTLE` and
`CLAUDE_CODE_USE_ANTHROPIC_AWS` is set, in the environment or in `env`.
With a Claude subscription, `claude setup-token` prints a long-lived `CLAUDE_CODE_OAUTH_TOKEN`.
`bare = true` reads neither that token nor a profile; use an API key with it. agent-ab never
copies your credentials file.

Isolation keeps your configuration out of the agent's context; it is not a sandbox (see
[safety.md](safety.md)). It cannot remove what an administrator deploys: managed settings and a
managed `CLAUDE.md` still apply. It was added after the published example runs and has not been
used for one yet. On 2026-11-06 it was checked without a credential, on Windows with Claude Code
2.1.308, which starts, prints its init event and stops at "Not logged in": auto memory lay in
the private config directory, Bash was available without `CLAUDE_CODE_GIT_BASH_PATH`, and an
`InstructionsLoaded` hook passed with `--settings` listed only the workspace's own `CLAUDE.md`.
An authenticated trial is still untested.

`isolation = false` runs the agent with your config directory and full environment, as
agent-ab 0.1.1 did. The leak check still records `config_leaks` (such trials normally list the
auto-memory directory inside your config directory) but does not fail the trial. Use it only on
a machine or account without user-level configuration.

## codex

Runs `codex exec` with JSON events. The prompt goes on stdin.

```text
codex exec --json --skip-git-repo-check --ephemeral -C <workspace>
           --sandbox <sandbox> | --dangerously-bypass-approvals-and-sandbox
           [-m M] [-c model_reasoning_effort=<effort>] [--ignore-user-config]
           <args...> -
```

| Key | Where | Default | Meaning |
|---|---|---|---|
| `model` | `[agent]` | CLI default | `-m`. |
| `effort` | `[agent]` | CLI default | `-c model_reasoning_effort=<effort>`. Accepted: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`. Which levels work depends on the model. |
| `executable` | options | `"codex"` | Name or path of the CLI. |
| `sandbox` | options | `"workspace-write"` | `--sandbox`: `read-only`, `workspace-write` or `danger-full-access`. |
| `bypass_sandbox` | options | `false` | Use `--dangerously-bypass-approvals-and-sandbox`. Excludes `sandbox`. Only inside a container or VM. |
| `ignore_user_config` | options | `false` | `--ignore-user-config`. |
| `price_input_per_mtok` | options | none | USD per million uncached input tokens. |
| `price_cached_input_per_mtok` | options | none | USD per million cached input tokens. |
| `price_output_per_mtok` | options | none | USD per million output tokens. |

Codex reports tokens, not cost. agent-ab computes cost only when the prices are set; without
them cost is unknown, cost ratios are not computed and `budget_usd` has no effect.

Notes:

- Set `ignore_user_config = true` so your local Codex configuration does not affect the arms.
- On Windows, if commands fail with a sandbox helper error, add
  `args = ["-c", "windows.sandbox=unelevated"]`.

```toml
[agent]
adapter = "codex"
model = "your-model"

[agent.options]
ignore_user_config = true
price_input_per_mtok = 1.25          # placeholders: use your model's current prices
price_cached_input_per_mtok = 0.125
price_output_per_mtok = 10.0
```

## command

Runs any command line. Use it for agents without a built-in adapter.

| Key | Where | Default | Meaning |
|---|---|---|---|
| `command` | `[agent]` | required | Argv template. |
| `model`, `effort` | `[agent]` | none | Available as `{model}` and `{effort}`. |
| `stdin` | options | `false` | Also send the prompt on stdin. |
| `shell` | options | `false` | Join the argv and run it through the shell. Refuses `{prompt}`. Discouraged. |

The prompt is always written to `prompt.md` in the attempt directory.

| Placeholder | Expands to |
|---|---|
| `{prompt_file}` | Path to `prompt.md`. |
| `{prompt}` | The prompt text as one argument. Can exceed command-line limits; prefer `{prompt_file}` or `stdin`. Not allowed with `shell = true`, or with a Windows batch file. |
| `{workspace}` | Workspace path (the working directory). |
| `{artifacts}` | Attempt directory. |
| `{root}` | Experiment directory (where `experiment.toml` lives). |
| `{model}`, `{effort}` | The arm's values, or empty. |
| `{python}` | Interpreter running agent-ab. |
| `{seed}` | The trial's seed. |

With `shell = true`, substituted values containing a newline are rejected, and on Windows
so are values containing `%`, `!` or `"`.

A non-zero exit code is recorded but is not an infrastructure error; the check decides.

### `usage.json`

To report usage, the command writes `{artifacts}/usage.json`, a JSON object with any of these
keys. Missing keys and wrong types are recorded as unknown.

| Key | Type | Meaning |
|---|---|---|
| `cost_usd` | number | Cost in USD. |
| `input_tokens`, `output_tokens` | integer | Tokens. |
| `cache_read_tokens`, `cache_write_tokens` | integer | Cache tokens. |
| `turns` | integer | Turns or model calls. |
| `final_message` | string | Final message. |
| `infra_error` | string | Marks the attempt as an infrastructure error. Use only for failures unrelated to the configuration. |

### Example: wrapping your own agent

`agents/wrap.py` sits next to `experiment.toml`, outside the workspace:

```python
"""Run my_agent.py for one trial and write usage.json."""

import json, re, subprocess, sys
from pathlib import Path

prompt_file, artifacts, model = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
agent = Path(__file__).with_name("my_agent.py")
proc = subprocess.run(
    [sys.executable, str(agent), "--model", model, "--prompt-file", str(prompt_file)],
    capture_output=True,
    text=True,
)
sys.stdout.write(proc.stdout)
sys.stderr.write(proc.stderr)

usage = {}
if m := re.search(r"TOKENS in=(\d+) out=(\d+)", proc.stdout):
    usage["input_tokens"], usage["output_tokens"] = int(m[1]), int(m[2])
if "rate limit" in proc.stderr.lower():
    usage["infra_error"] = "rate limited"
(artifacts / "usage.json").write_text(json.dumps(usage), encoding="utf-8")
sys.exit(proc.returncode)
```

```toml
[agent]
adapter = "command"
command = ["{python}", "{root}/agents/wrap.py", "{prompt_file}", "{artifacts}", "{model}"]

[[arms]]
name = "small"
[arms.agent]
model = "small-model"

[[arms]]
name = "large"
[arms.agent]
model = "large-model"
```

Do not deliver the wrapper through an `overlay`: the agent would see it.

## mock

A fake agent for demos and tests. Offline and deterministic for a given trial seed. On
success it copies the task's `solution/` over the workspace; on failure it leaves the
workspace alone or writes a wrong file. A task without `solution/` always fails. It does not
accept `args`.

| Option | Default | Meaning |
|---|---|---|
| `solve_rate` | `0.5` | Probability of solving a task. |
| `task_rates` | `{}` | Per-task `solve_rate` overrides. |
| `cost_usd` | `0.01` | Simulated cost: a number or `[low, high]`. |
| `duration_s` | `0` | Seconds to sleep: a number or `[low, high]`. |
| `tokens` | `1000` | Simulated token count. |
| `fail_mode` | `"revert"` | `"revert"` leaves the workspace untouched; `"break"` writes a wrong file. |
| `infra_error_rate` | `0` | Probability of an infrastructure error. |
| `crash_rate` | `0` | Probability of exiting non-zero. |

Use it to test a new task suite and the whole pipeline for free.

## Adding an adapter

1. Subclass `agent_ab.adapters.base.Adapter` in `src/agent_ab/adapters/<name>.py`:
   - `name`: the value used in `adapter = "..."`;
   - `option_keys`: accepted `[agent.options]` keys;
   - `validate(spec)`: return a list of problems; no side effects;
   - `check_available(spec)`: return a message if the agent cannot be launched, else `None`;
   - `check_workspace_root(spec, root)` (optional): return a message if workspaces under `root`
     would expose the agent to files it must not see, else `None`;
   - `build(ctx)`: return an `AgentInvocation` (argv, env, stdin, cwd; optionally `base_env`
     to replace the inherited environment and `temp_dirs` for the runner to remove after the
     agent exits);
   - `parse(ctx, result)`: return `AgentUsage`. It must never raise. Set `infra_error` only
     for failures unrelated to the configuration under test.
2. Register it in `_REGISTRY` in `src/agent_ab/adapters/__init__.py` as
   `"name": "agent_ab.adapters.<module>:<Class>"`.
3. Add offline tests that feed `parse` recorded output, and document the options here.

Adapters are stateless: one instance serves every trial, possibly from several threads. The
built-in adapters are short; read `adapters/claude_code.py` for a complete example. See
[CONTRIBUTING.md](../CONTRIBUTING.md).
