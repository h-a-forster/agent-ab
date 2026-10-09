# Safety

agent-ab launches coding agents unattended, many times, often in parallel. Nobody is there
to approve a tool call or stop a bad command. Plan for that.

## Permissions

An unattended agent cannot wait for approval, so the built-in adapters default to modes that
do not ask:

- `claude-code` uses `permission_mode = "bypassPermissions"`.
- `codex` uses `sandbox = "workspace-write"`; `bypass_sandbox = true` removes Codex's sandbox
  entirely.
- `command` runs whatever you configure, with your permissions.

In these modes the agent can run any command your user account can run.

## What isolation you get, and what you don't

Each trial runs in a fresh temporary directory, and the agent's working directory is set to
it. That keeps trials from seeing each other's files and makes cleanup easy.

**The workspace is not a sandbox.** Nothing stops an agent from leaving it. An agent can:

- read and write anything your user account can, including your home directory, SSH keys,
  cloud credentials, browser profiles and other projects;
- use credentials in its environment and configuration files (API keys, `gh` and cloud CLI
  logins, git credential helpers);
- use the network: download and run code, push to remotes, call APIs;
- start processes that outlive the trial (agent-ab kills the process tree it started on
  timeout or Ctrl-C, but a process that detaches itself can escape that);
- read the task directories themselves, **including `checks/` and `solution/`**, because they
  are on the same file system. The hidden check is hidden from the workspace, not from a
  determined agent.

The process environment is your environment plus `env` from the configuration. Anything
exported in the shell you run agent-ab from is visible to every agent.

## Run experiments in a container or VM

The simplest robust setup is a container (or a disposable VM) that holds only what the
experiment needs:

- no personal files, SSH keys or cloud credentials;
- only the API key the agent needs, ideally one created for experiments with a spending
  limit set at the provider;
- the experiment directory mounted read-only, and a separate writable directory for runs;
- a non-root user.

A minimal Dockerfile for Claude Code experiments:

```dockerfile
FROM python:3.12-slim

# Node.js is needed for the Claude Code CLI; git lets agent-ab record diffs.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git nodejs npm \
 && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code \
 && pip install --no-cache-dir agent-ab

RUN useradd --create-home runner
USER runner
WORKDIR /home/runner
```

Build it and run an experiment, passing only the API key:

```sh
docker build -t agent-ab-runner .
docker run --rm -it \
  -e ANTHROPIC_API_KEY \
  -v "$PWD/my-experiment:/experiment:ro" \
  -v "$PWD/runs:/runs" \
  agent-ab-runner \
  agent-ab run /experiment/experiment.toml --out /runs/run-1
```

To resume, run the same command with `--resume /runs/run-1` instead of `--out /runs/run-1`.

Notes:

- `-e ANTHROPIC_API_KEY` without a value passes the variable from your shell without writing
  it on the command line.
- The read-only mount stops agents from modifying your tasks, but they can still read them,
  including hidden checks. If that matters for your experiment, review the agent transcripts
  (`agent.stdout`) for access to paths outside the workspace.
- A container shares the host kernel. For stronger isolation use a VM.
- To restrict the network, attach the container to a network that only allows the model
  provider's API, for example through an egress proxy.

## Budgets

Unattended agents can spend money quickly, especially with `jobs > 1`.

- **`budget_usd`** (or `--budget`): agent-ab stops launching new trials once the cost
  recorded in the run directory reaches the budget. Trials already running finish, so spend
  can exceed the budget by up to `jobs` trials. On resume, earlier spend counts.
- **Per-trial limits**: `max_budget_usd` and `max_turns` for `claude-code`; `timeout_s` for
  every adapter.
- **Cost must be reported to be counted.** The budget only sees costs the adapter reports.
  `codex` reports cost only when you set token prices; `command` only when your wrapper
  writes `cost_usd` to `usage.json`. Otherwise the budget does not limit anything.
- **Provider limits** are the last line of defence. Set a spending limit on the API key.
- **Dry-run first.** `agent-ab run experiment.toml --dry-run` prints the planned trial count
  without running anything. Multiply by your expected cost per trial.

## Secrets hygiene

- Do not put API keys in `experiment.toml`. `env` values are stored in plain text in
  `run.json` (as part of the resolved configuration) and the configuration is often
  committed. Pass secrets through the environment of the process that runs agent-ab instead.
- Run directories contain full agent transcripts (`agent.stdout`, `agent.stderr`) and diffs.
  If an agent printed a secret, it is in there. Review run directories before sharing them.
- Do not commit `runs/` to a public repository without reviewing it.
- `keep_workspaces = true` leaves agent workspaces on disk; delete them when done.

## Untrusted tasks and configurations

A task's prompt, starting files, `setup` command and `check` command all run with your
permissions, and the prompt instructs an agent that has full permissions. Treat a task suite
from someone else like any other code you are about to execute: read it first, and run it in
a container.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md).
