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

Agents inherit your environment plus `env` from the config, so anything exported in your
shell is visible to them. The exception is `claude-code` with `isolation` (the default), which
passes only an allow-list (system basics, proxies, API credentials) plus `env`; see
[adapters.md](adapters.md#isolation).

## Grading integrity

The checks import the agent's code, so the agent's files can try to influence grading. agent-ab
closes these routes:

- **Clean copy.** The checks never run in the workspace the agent edited. agent-ab builds a fresh
  workspace from the pristine task (the arm's removals and overlay, then the task's `setup`),
  applies the agent's recorded diff (`diff.patch`) with `git apply`, and copies the hidden
  `checks/` on top. Nothing outside that diff reaches the checks: interpreter caches (including
  a forged `.pyc` that Python would load instead of the source), files written after the diff
  was taken, or the agent's `.git`. git refuses patch paths outside the work tree. A diff that
  does not apply fails the trial. If the agent breaks the workspace's `.git` so that no diff
  can be recorded, the trial fails rather than falling back to grading in place; the error says
  whether `.git` was missing or replaced or git itself could not record the changes. A failure
  to write `diff.patch` into the run directory is an infrastructure error and is retried, as is
  any grading failure the machine caused: git reporting a full disk or no memory, git hitting its
  time limit when the agent did not add enough to explain it, a valid diff that cannot be written
  to the clean copy, or a step that also fails on a copy of the task the agent never touched.
- **What an agent can still turn from a `fail` into an excluded error.** Agents run with full
  permissions and machine failures must not count against them, so these remain. No route gives a
  pass, and retries are bounded, but the trial leaves the denominator, which can lift a pass rate.
  The report counts errors per arm: compare them before trusting a difference.
  - Filling the disk or exhausting memory while git records its diff.
  - Killing its own CLI, so that no result is written (`claude-code`), or writing `infra_error`
    to `usage.json` when it knows `{artifacts}` (`command`).
  - Changing anything outside its workspace that grading needs: the task's `checks/` or `repo/`
    folder, which breaks every later trial too and so stops the run after ten errors, or the run
    directory, so that `diff.patch` cannot be written.
  - Adding just under what counts as enough to stall git (about 20,000 files or 2 GiB at the 600 s
    limit) on a machine slow enough to time out anyway. The figures are a third of what one Windows PC
    measured.
  - On Linux and macOS, a file name containing a newline can put a line of its own choosing in
    git's error output, ending in a phrase such as `: No space left on device`.

  The other way round, a machine failure can still read as the agent's: a disk that fills while the
  check runs, including when the verifying runner cannot write its report, is a failing check. So
  is a machine stall on a workspace the agent did add that much to, and a spend limit reached
  mid-trial in wording agent-ab does not recognise.

  Closed: a file name that merely contains such a phrase, a command line overflowed by staged
  entries, a workspace bloated with what the agent added (`npm install` included) until git times
  out, and an API 400 its work provoked (a context overflow) all stay `fail`.
  Nested git repositories the agent creates (a `git clone` to vendor a library, `git init` in a
  subdirectory) are recorded as ordinary files: their `.git` metadata is moved aside while the
  diff is taken and does not reach the grading copy, and gitlink entries the agent staged for
  them (`git add` of a nested repository, `git submodule add`) are dropped from the index. A
  stale `.git/index.lock`, left by a git command killed with the agent, is removed first. Only
  what git records reaches the checks: empty directories do not, a case-only rename is lost on
  case-insensitive filesystems (Windows, macOS), and a file git cannot read fails the trial.
  Without git on the host there is no diff, and the checks run in the agent's workspace.
- **Verified exit status.** Agent code can force the check's exit status: an `atexit` hook that
  calls `os._exit(0)`, or `sys.exit(0)` while a test module named on the command line is
  imported (unittest's discovery already reports that as an error). Argv checks of the form
  `["{python}", "-m", "unittest", ...]` therefore run under `agent_ab.checkrun`, a drop-in for
  `python -m unittest`. Before any test code is imported it takes a report path and a one-time
  nonce out of its environment; after the run it writes the counts and the nonce to the
  attempt's `check-report.json`. A zero exit status passes only with a report that carries the
  nonce and shows at least one test run and no failures, errors, unexpected successes or skips
  (agent code can raise `SkipTest`). Other check commands are judged by exit status alone.
- **Safe path.** Every check command runs with `PYTHONSAFEPATH=1` (the environment form of
  `python -P`), so `python -m ...` and script runs do not put the workspace first on `sys.path`.
  An agent-written `unittest/` package cannot shadow the standard library.
- **Check-only paths.** Before the hidden `checks/` are copied in, every top-level entry of
  them that is absent from the task's `repo/` is removed (links are unlinked, not followed). A
  file the agent planted next to the real checks, such as `checks/test_aaa.py`, does not run.

Residual risks:

- The verified exit status stops generic exit forcing, not code aimed at agent-ab. Agent code
  runs inside the check process, so it can monkeypatch `unittest`, or find the report path and
  nonce and write a clean report itself: a few lines that walk the interpreter's stack frames
  to the runner's locals are enough, and on Linux both values stay readable in
  `/proc/self/environ` after they are removed from `os.environ`. Treat a clean report as
  evidence against accidental or generic tampering only; real isolation needs a sandbox, and
  the diffs of surprising passes should be read.
- agent-ab records the diff with git commands run on the agent's own `.git`, outside the agent's
  process cleanup. Before recording, it resets the repository config and removes
  `.git/info/attributes`, so a filter driver the agent configured (a `.gitattributes` entry
  plus a `filter.*.clean` command) does not run. That covers this known route, not every way
  an agent that edits `.git` internals could target agent-ab's git commands.
- Modules the checks import after discovery can still be shadowed by workspace files of the same
  name.
- An agent with full filesystem access can alter the interpreter's `site-packages`, the task
  directory or agent-ab itself.

Mitigate these with a sandbox (see below) and by reading the diffs of passing trials, especially
surprising passes.

Apart from the no-tests re-run, the published results in [results.md](results.md) predate the
clean copy and the verified exit status: their checks ran in the agent's workspace, judged by
exit status. They have not been re-graded.

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
