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
- adds `env` to the inherited environment and appends `args` after its own arguments;
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
  `plugins`, `skills` and `agents`.
- `init.json` in the attempt directory: the full init event, without `cwd`, `session_id`,
  `uuid`, `scratchpad_path`, `messaging_socket_path`, `startup_timing` and any value that is
  an absolute path. The event is read from the start of the output, so a long transcript does
  not hide it.

The report lists the models, versions and, when init data exists, the number of tools, MCP
servers and plugins per arm, and notes arms that used more than one model, a model other than
the one requested, or a different tool, MCP or plugin set (a confound unless that difference
is what you are testing). Runs without this data produce the same report as before.

Isolation: Claude Code also loads settings from your home directory. Set
`setting_sources = "project"` so only workspace settings apply, which is what you want when
the arm difference is a workspace file such as a `CLAUDE.md`. To compare a customised setup
with a stock one, use an arm with `safe_mode = true` (or `bare = true`). `strict_mcp_config`
keeps your own MCP servers out, and the recorded init summary lets you check what was
actually loaded: compare `tools`, `mcp_servers`, `plugins` and `skills` across arms.

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
   - `build(ctx)`: return an `AgentInvocation` (argv, env, stdin, cwd);
   - `parse(ctx, result)`: return `AgentUsage`. It must never raise. Set `infra_error` only
     for failures unrelated to the configuration under test.
2. Register it in `_REGISTRY` in `src/agent_ab/adapters/__init__.py` as
   `"name": "agent_ab.adapters.<module>:<Class>"`.
3. Add offline tests that feed `parse` recorded output, and document the options here.

Adapters are stateless: one instance serves every trial, possibly from several threads. The
built-in adapters are short; read `adapters/claude_code.py` for a complete example. See
[CONTRIBUTING.md](../CONTRIBUTING.md).
