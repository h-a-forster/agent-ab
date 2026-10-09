# Adapters

An adapter turns an arm's agent settings into a process invocation and reads back what the
agent spent. Choose one with `adapter = "..."` in `[agent]` or `[arms.agent]`.

| Adapter | Agent | Reports cost | Network |
|---|---|---|---|
| [`claude-code`](#claude-code) | Claude Code CLI (`claude`) | yes | yes |
| [`codex`](#codex) | Codex CLI (`codex exec`) | only if you set prices | yes |
| [`command`](#command) | anything with a command line | via `usage.json` | up to you |
| [`mock`](#mock) | built-in fake agent | simulated | no |

Every adapter:

- runs the agent with the workspace as its working directory;
- applies `[agent].env` on top of the inherited environment;
- appends `args` after its own arguments;
- validates `[agent.options]` when the configuration is loaded (unknown option keys are
  errors);
- checks that the agent's executable is available before a run starts, and fails fast with
  a message if it is not.

The agent's stdout and stderr are saved as `agent.stdout` and `agent.stderr` in the attempt
directory (see [run-directory.md](run-directory.md)).

**Infrastructure errors.** When an adapter recognises a failure that has nothing to do with
the configuration under test (authentication, rate limits, provider overload, network
resets), it marks the attempt as an infrastructure error. The attempt is retried up to
`max_retries` times and, if it never succeeds, excluded from statistics and reported. An
agent that simply fails the task, gives up, or exits non-zero is *not* an infrastructure
error.

## claude-code

Runs Claude Code in print mode with JSON output. The prompt is sent on stdin.

The command line is built as:

```text
claude -p --output-format json --no-session-persistence
       --permission-mode <permission_mode>
       [--model <model>] [--effort <effort>]
       [--max-budget-usd <max_budget_usd>] [--max-turns <max_turns>]
       [--safe-mode] [--bare] [--setting-sources <setting_sources>]
       [--append-system-prompt <append_system_prompt>]
       <args...>
```

| Key | Where | Type | Default | Meaning |
|---|---|---|---|---|
| `model` | `[agent]` | string | CLI default | `--model`. |
| `effort` | `[agent]` | string | CLI default | `--effort`. One of `low`, `medium`, `high`, `xhigh`, `max`. |
| `executable` | options | string | `"claude"` | Name or path of the CLI. |
| `permission_mode` | options | string | `"bypassPermissions"` | `--permission-mode`. Unattended runs need a mode that does not wait for approval. |
| `max_budget_usd` | options | float | none | `--max-budget-usd`: per-trial spend cap enforced by the CLI. |
| `max_turns` | options | integer | none | `--max-turns`. |
| `safe_mode` | options | boolean | `false` | `--safe-mode`: start with customizations (instruction files, skills, plugins, hooks, MCP servers) disabled. |
| `bare` | options | boolean | `false` | `--bare`: minimal mode. Note that it changes how the CLI authenticates; see the CLI's own help. |
| `setting_sources` | options | string | none | `--setting-sources`, e.g. `"project"` to load only settings from the workspace. |
| `append_system_prompt` | options | string | none | `--append-system-prompt`. |

From the JSON result it records cost (`total_cost_usd`), turns, input/output tokens, cache
read and cache write tokens, and the final message. A trial that ends because it hit
`max_turns` or `max_budget_usd` is a normal failure, not an infrastructure error.

**Isolating the variable.** Claude Code loads configuration from your home directory as well
as from the workspace. That configuration applies to every arm equally, but it is part of
what you are measuring and makes the experiment hard to reproduce elsewhere. When the arm
difference is a workspace file (for example a `CLAUDE.md` delivered by `overlay`), consider
`setting_sources = "project"`. When comparing a customised setup against a stock one, an arm
with `safe_mode = true` is a convenient baseline.

```toml
[agent]
adapter = "claude-code"
model = "sonnet"
effort = "medium"

[agent.options]
permission_mode = "bypassPermissions"
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

Runs `codex exec` with JSON event output. The prompt is sent on stdin.

```text
codex exec --json --skip-git-repo-check --ephemeral -C <workspace>
           --sandbox <sandbox>            (or --dangerously-bypass-approvals-and-sandbox)
           [-m <model>] [-c model_reasoning_effort="<effort>"]
           [--ignore-user-config]
           <args...> -
```

| Key | Where | Type | Default | Meaning |
|---|---|---|---|---|
| `model` | `[agent]` | string | CLI default | `-m`. |
| `effort` | `[agent]` | string | CLI default | Sets `model_reasoning_effort`. |
| `executable` | options | string | `"codex"` | Name or path of the CLI. |
| `sandbox` | options | string | `"workspace-write"` | `--sandbox` mode. |
| `bypass_sandbox` | options | boolean | `false` | Use `--dangerously-bypass-approvals-and-sandbox` instead of `--sandbox`. Only inside a container or VM. |
| `ignore_user_config` | options | boolean | `false` | `--ignore-user-config`. |
| `price_input_per_mtok` | options | float | none | USD per million uncached input tokens. |
| `price_cached_input_per_mtok` | options | float | none | USD per million cached input tokens. |
| `price_output_per_mtok` | options | float | none | USD per million output tokens. |

The Codex CLI reports tokens but not cost. agent-ab sums token usage over the run's turns
and computes cost only when you set the prices. Without prices, cost is reported as unknown,
cost ratios are not computed, and `budget_usd` has no effect.

```toml
[agent]
adapter = "codex"
model = "your-model"

[agent.options]
sandbox = "workspace-write"
ignore_user_config = true
price_input_per_mtok = 1.25
price_cached_input_per_mtok = 0.125
price_output_per_mtok = 10.0
```

The prices above are placeholders. Use the current prices for your model.

## command

Runs any command line you give it. Use it for agents without a built-in adapter, or to wrap
an agent in your own script.

| Key | Where | Type | Default | Meaning |
|---|---|---|---|---|
| `command` | `[agent]` | list of strings | required | Argv template. Must not be empty. |
| `model`, `effort` | `[agent]` | string | none | Available as `{model}` and `{effort}`. |
| `stdin` | options | boolean | `false` | Also send the prompt on stdin. |
| `shell` | options | boolean | `false` | Join the argv and run it through the shell. Discouraged: quoting differs between platforms. |

The prompt is always written to `prompt.md` in the attempt directory before the command
runs.

Placeholders in `command`:

| Placeholder | Expands to |
|---|---|
| `{prompt_file}` | Path to `prompt.md` in the attempt directory. |
| `{prompt}` | The prompt text itself, as one argument. Long prompts can exceed command-line length limits, especially on Windows; prefer `{prompt_file}` or `stdin`. |
| `{workspace}` | The workspace path (also the working directory). |
| `{artifacts}` | The attempt directory, where `usage.json` is read from. |
| `{model}` | The arm's `model`, or empty. |
| `{effort}` | The arm's `effort`, or empty. |
| `{python}` | The Python interpreter running agent-ab. |
| `{seed}` | The trial's deterministic seed. |

Write literal braces as `{{` and `}}`. An unknown placeholder is a configuration error.

The exit code is recorded. A non-zero exit is **not** an infrastructure error; the hidden
check decides pass or fail.

### The `usage.json` contract

To report what a trial spent, have the command write `{artifacts}/usage.json`: a JSON object
with any of these keys. Missing keys, and values of the wrong type, are recorded as unknown.

| Key | Type | Meaning |
|---|---|---|
| `cost_usd` | number | Cost of the attempt in USD. |
| `input_tokens` | integer | Input tokens. |
| `output_tokens` | integer | Output tokens. |
| `cache_read_tokens` | integer | Input tokens served from a cache. |
| `cache_write_tokens` | integer | Tokens written to a cache. |
| `turns` | integer | Agent turns or model calls. |
| `final_message` | string | The agent's final message. |
| `infra_error` | string | Set this to mark the attempt as an infrastructure error (retried, then excluded). Use it only for failures unrelated to the configuration under test. |

If the file is absent, all usage values are unknown.

### Worked example: wrapping your own agent

Suppose you have an agent script, `my_agent.py`, that takes a prompt and edits files in the
current directory, and prints a final line like `TOKENS in=1234 out=567`. A wrapper adapts
it to the contract:

`agents/wrap_my_agent.py`:

```python
"""Run my_agent.py on one agent-ab trial and write usage.json."""

import json
import re
import subprocess
import sys
from pathlib import Path

prompt_file, artifacts, model = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
agent = Path(__file__).with_name("my_agent.py")

proc = subprocess.run(
    [sys.executable, str(agent), "--model", model, "--prompt", prompt_file.read_text("utf-8")],
    capture_output=True,
    text=True,
)
sys.stdout.write(proc.stdout)
sys.stderr.write(proc.stderr)

usage: dict = {}
m = re.search(r"TOKENS in=(\d+) out=(\d+)", proc.stdout)
if m:
    usage["input_tokens"], usage["output_tokens"] = int(m[1]), int(m[2])
    # Example prices; replace with your model's.
    usage["cost_usd"] = usage["input_tokens"] * 3e-6 + usage["output_tokens"] * 15e-6
if "rate limit" in proc.stderr.lower():
    usage["infra_error"] = "rate limited"

(artifacts / "usage.json").write_text(json.dumps(usage), encoding="utf-8")
sys.exit(proc.returncode)
```

`experiment.toml`:

```toml
name = "my-agent-models"
tasks = ["tasks/*"]
repeats = 3

[agent]
adapter = "command"
command = ["{python}", "/opt/agents/wrap_my_agent.py", "{prompt_file}", "{artifacts}", "{model}"]

[[arms]]
name = "small"
[arms.agent]
model = "small-model"

[[arms]]
name = "large"
[arms.agent]
model = "large-model"
```

The command runs with the workspace as its working directory, so refer to the wrapper by an
absolute path (here `/opt/agents/`; use the location on your machine or in your container).
Do not deliver the wrapper through an `overlay`: the agent would see it in the workspace.
`{python}` runs the wrapper with the same interpreter as agent-ab on every platform.

## mock

A built-in fake agent for demos and tests. It needs no network and is deterministic for a
given trial seed. On success it copies the task's `solution/` over the workspace; on failure
it either leaves the workspace untouched or writes a wrong file. A task without `solution/`
always fails. It reports simulated cost and tokens through `usage.json`.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `solve_rate` | float in [0, 1] | `0.5` | Probability of solving a task. |
| `task_rates` | table of task id to float | `{}` | Per-task `solve_rate` overrides, to simulate task difficulty. |
| `cost_usd` | float or `[low, high]` | `0.01` | Simulated cost, fixed or uniform in a range. |
| `duration_s` | float or `[low, high]` | `0` | Seconds to sleep. |
| `tokens` | integer | `1000` | Simulated token count. |
| `fail_mode` | `"revert"` or `"break"` | `"revert"` | On failure, leave the workspace untouched or write a wrong file. |
| `infra_error_rate` | float in [0, 1] | `0` | Probability of reporting an infrastructure error. |
| `crash_rate` | float in [0, 1] | `0` | Probability of exiting non-zero. |

The mock adapter is useful for checking a new task suite and the whole pipeline before you
spend money:

```toml
[agent]
adapter = "mock"

[[arms]]
name = "control"
[arms.agent.options]
solve_rate = 0.5

[[arms]]
name = "treatment"
[arms.agent.options]
solve_rate = 0.7
cost_usd = [0.02, 0.05]
```

## Adding an adapter

Adapters subclass `agent_ab.adapters.base.Adapter`:

```python
from agent_ab.adapters.base import Adapter, read_text
from agent_ab.model import AgentInvocation, AgentSpec, AgentUsage, ProcResult, TrialContext


class MyAgentAdapter(Adapter):
    name = "my-agent"
    option_keys = frozenset({"executable"})

    def validate(self, spec: AgentSpec) -> list[str]:
        problems = super().validate(spec)  # rejects unknown option keys
        if spec.effort not in (None, "low", "high"):
            problems.append(f"effort must be 'low' or 'high', got {spec.effort!r}")
        return problems

    def check_available(self, spec: AgentSpec) -> str | None:
        # Return a message if the executable cannot be found, else None.
        return None

    def build(self, ctx: TrialContext) -> AgentInvocation:
        exe = ctx.spec.options.get("executable", "my-agent")
        argv = [exe, "--non-interactive"]
        if ctx.spec.model:
            argv += ["--model", ctx.spec.model]
        argv += list(ctx.spec.args)
        return AgentInvocation(argv=argv, env=dict(ctx.spec.env), stdin=ctx.prompt)

    def parse(self, ctx: TrialContext, result: ProcResult) -> AgentUsage:
        usage = AgentUsage()
        # read_text(result.stdout_path) returns the captured stdout; extract usage from it.
        # Parse leniently: parse() must never raise on malformed output.
        if "401 Unauthorized" in read_text(result.stderr_path, limit=4000):
            usage.infra_error = "authentication failed"
        return usage
```

The contract:

- **`name`** is the value used in `adapter = "..."`.
- **`option_keys`** lists the keys accepted under `[agent.options]`.
- **`validate(spec)`** returns a list of problems (empty = valid) and has no side effects.
  It runs when the configuration is loaded.
- **`check_available(spec)`** returns a message if the agent cannot be launched on this
  machine. It runs once before a run starts.
- **`build(ctx)`** returns the argv, environment additions, optional stdin text and optional
  working directory (default: the workspace). It may write files under `ctx.artifacts`.
- **`parse(ctx, result)`** reads the captured output (`result.stdout_path`,
  `result.stderr_path`, files in `ctx.artifacts`) and returns `AgentUsage`. It must never
  raise. Set `infra_error` only for failures unrelated to the configuration under test.
- Adapters are stateless; one instance serves every trial, possibly from several threads.

Register the adapter in the `ADAPTERS` dictionary in `src/agent_ab/adapters/__init__.py`,
add tests in `tests/` that run without the real agent (feed `parse` recorded output), and
document its options on this page. See [CONTRIBUTING.md](../CONTRIBUTING.md).
