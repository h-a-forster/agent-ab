# Safety

agent-ab runs coding agents unattended, many times, often in parallel. Nobody approves tool
calls or stops a bad command.

## Permissions

The built-in adapters default to modes that do not ask for approval:

- `claude-code`: `permission_mode = "bypassPermissions"`.
- `codex`: `sandbox = "workspace-write"`. `bypass_sandbox = true` removes the sandbox.
- `command`: runs whatever you configure, with your permissions.

## The workspace is not a sandbox

Each trial runs in a fresh temporary directory. That separates trials and makes cleanup
easy. It does not contain the agent. An agent can:

- read and write anything your user account can: home directory, SSH keys, cloud
  credentials, other projects;
- use credentials in its environment and config files (API keys, `gh` logins, git
  credential helpers);
- use the network;
- read the task directories, including `checks/` and `solution/`.

agent-ab kills leftover agent processes after every trial (job objects on Windows, process
groups on Linux and macOS). A process that deliberately escapes these can survive.

Agents inherit your environment plus `env` from the config. Anything exported in your shell
is visible to every agent.

## Grading integrity

The check runs in the workspace the agent edited, so the agent's files can try to influence it.
Two routes are closed:

- Every check command runs with `PYTHONSAFEPATH=1` (the environment form of `python -P`), so
  `python -m ...` and script runs do not put the workspace first on `sys.path`. An agent-written
  `unittest/` package can no longer shadow the standard library.
- Before the hidden `checks/` are copied in, every top-level entry of them that is absent from the
  task's `repo/` is removed from the workspace (links are unlinked, not followed). A file the
  agent planted next to the real checks, such as `checks/test_aaa.py`, does not run.

Residual risks:

- The checks import the agent's own code, which can exit the process or monkeypatch things at
  import time.
- Modules the checks import after discovery can still be shadowed by workspace files of the same
  name.
- An agent with full filesystem access can alter the interpreter's `site-packages`.

Mitigate these with a sandbox (see below) and by reading the diffs of passing trials, especially
surprising passes.

## Use a container or VM

Run experiments in a container or disposable VM that holds:

- no personal files, SSH keys or cloud credentials;
- only the API key the agent needs, ideally a dedicated key with a provider spending limit;
- the experiment directory mounted read-only and a separate writable directory for runs;
- a non-root user.

A minimal Dockerfile for Claude Code:

```dockerfile
FROM python:3.12-slim

# Node.js for the Claude Code CLI; git for recording diffs.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git nodejs npm \
 && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code \
 && pip install --no-cache-dir git+https://github.com/h-a-forster/agent-ab

RUN useradd --create-home runner
USER runner
WORKDIR /home/runner
```

```sh
docker build -t agent-ab-runner .
docker run --rm -it \
  -e ANTHROPIC_API_KEY \
  -v "$PWD/my-experiment:/experiment:ro" \
  -v "$PWD/runs:/runs" \
  agent-ab-runner \
  agent-ab run /experiment/experiment.toml --out /runs/run-1
```

To resume, replace `--out /runs/run-1` with `--resume /runs/run-1`.

- `-e ANTHROPIC_API_KEY` without a value passes the variable from your shell.
- The read-only mount stops agents from changing your tasks, not from reading them.
- A container shares the host kernel. Use a VM for stronger isolation.
- To restrict the network, use a container network that only reaches the model provider,
  for example through an egress proxy.

## Budgets

- `budget_usd` (or `--budget`, must be > 0): no new trials start once recorded spend reaches
  it. Running trials finish, so spend can exceed it by up to `jobs` trials. Earlier sessions
  of a resumed run count.
- Per-trial limits: `max_budget_usd` and `max_turns` for `claude-code`; `timeout_s` for every
  adapter.
- Only reported cost counts. `codex` reports cost only with token prices set; `command` only
  if your wrapper writes `cost_usd`. A trial that times out may report no cost.
- Set a spending limit on the API key at the provider.
- Run `agent-ab run experiment.toml --dry-run` first to see the trial count.

## Secrets

- Do not put API keys in `experiment.toml`. `env` values are redacted in `run.json`, but the
  config file itself is often committed. Pass secrets through the environment.
- Run directories hold full agent output and diffs. If an agent printed a secret, it is
  there. Review run directories before sharing them.
- `keep_workspaces = true` leaves workspaces on disk; delete them when done.

## Untrusted tasks

A task's prompt, files, `setup` and `check` run with your permissions, and the prompt
instructs an agent with full permissions. Read a task suite before running it, and run it in
a container.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md).
