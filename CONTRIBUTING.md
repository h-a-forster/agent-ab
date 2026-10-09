# Contributing

Bug reports, adapters, example tasks and documentation fixes are welcome.

## Setup

You need [uv](https://docs.astral.sh/uv/) and git. From a clone:

```sh
uv sync --group dev
uv run agent-ab --version
```

## Tests and lint

```sh
uv run pytest
uv run ruff check .
```

CI runs both on Linux, macOS and Windows with Python 3.11-3.13, and smoke-tests a built wheel
with the offline demo.

Tests must run offline and fast: no real agents, no network. Use the `mock` adapter or a fake
agent started with `sys.executable`. Write files only under pytest's `tmp_path`. Tests must
pass on Windows: use `pathlib` and do not assume `sh`.

## Code

- Python 3.11+, standard library only at runtime. Open an issue before adding a dependency.
- Shared types are in `src/agent_ab/model.py`, errors in `src/agent_ab/errors.py`.
- Match the surrounding style; ruff enforces the rest (line length 100).
- Write text files as UTF-8.

## Adapters

See [docs/adapters.md](docs/adapters.md#adding-an-adapter). Register the class in `_REGISTRY`
in `src/agent_ab/adapters/__init__.py` and add `tests/test_adapter_<name>.py` that tests
`build` and `parse` against recorded output, including each kind of infrastructure error.
`parse` must never raise. Mark a failure as an infrastructure error only if it is unrelated
to the configuration under test; otherwise it is silently dropped from the statistics.

Consider whether the `command` adapter with a wrapper script is enough first.

## Tasks

Example tasks go under `examples/tasks/`. Each needs `task.toml`, hidden checks in `checks/`
and a `solution/`. Every task must fail before and pass after its solution on every
platform:

```sh
uv run agent-ab validate examples/quickstart/experiment.toml --tasks
```

See [docs/tasks.md](docs/tasks.md).

## Pull requests

- One change per pull request, with tests and docs.
- Add an entry under "Unreleased" in [CHANGELOG.md](CHANGELOG.md) for user-visible changes.
- `uv run pytest` and `uv run ruff check .` must pass.

Security issues: see [SECURITY.md](SECURITY.md). Do not open a public issue.
