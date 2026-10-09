# Contributing

Thanks for helping. Bug reports, task-suite examples, adapters and documentation fixes are
all welcome.

## Development setup

You need [uv](https://docs.astral.sh/uv/) and git. From a clone of the repository:

```sh
uv sync --group dev
```

This creates `.venv` with agent-ab installed in editable mode, plus pytest and ruff. Run the
CLI from the checkout with:

```sh
uv run agent-ab --version
```

## Tests and lint

```sh
uv run pytest
uv run ruff check .
```

To run one file:

```sh
uv run pytest tests/test_stats.py
```

CI runs both on Linux, macOS and Windows with Python 3.11, 3.12 and 3.13, and smoke-tests a
built wheel with the offline demo. See [.github/workflows/ci.yml](.github/workflows/ci.yml).

Test rules:

- Tests run offline and fast. No real agents, no network. Use the `mock` adapter or a fake
  agent script started with `sys.executable`.
- Use pytest's `tmp_path` for files. Never write outside it.
- Tests must pass on Windows: use `pathlib`, do not assume `sh`, and do not hard-code path
  separators.

## Code guidelines

- Python 3.11+, **standard library only** at runtime. Adding a runtime dependency needs a
  strong reason; discuss it in an issue first.
- Shared types live in `src/agent_ab/model.py` and errors in `src/agent_ab/errors.py`.
- Public functions have docstrings. Comments explain why, briefly.
- Match the surrounding style; ruff enforces the rest (line length 100).
- Write text files as UTF-8.

## Adding an adapter

1. Create `src/agent_ab/adapters/<name>.py` with a subclass of
   `agent_ab.adapters.base.Adapter`. Implement `build` and `parse`; override `validate` and
   `check_available` as needed. See [docs/adapters.md](docs/adapters.md#adding-an-adapter).
2. Register it in `ADAPTERS` in `src/agent_ab/adapters/__init__.py`.
3. Add `tests/test_adapter_<name>.py`. Test `build` (argv, stdin, env for each option) and
   `parse` against recorded outputs: success, malformed output, and each kind of
   infrastructure error. Do not call the real agent.
4. Document the options in [docs/adapters.md](docs/adapters.md).

`parse` must never raise, and must set `infra_error` only for failures unrelated to the
configuration under test (authentication, rate limits, outages). Classifying a genuine agent
failure as an infrastructure error silently drops it from the statistics.

If an agent can run from a command line, consider whether the `command` adapter with a small
wrapper script is enough before adding a built-in adapter.

## Adding tasks and examples

Example task suites go under `examples/`. Each task needs a `task.toml`, hidden checks in
`checks/`, and a reference `solution/`. Before submitting:

```sh
uv run agent-ab validate examples/<suite>/experiment.toml --tasks
```

Every task must fail before and pass after its solution, on every platform. Use `{python}`
and argv lists in `check` and `setup`, keep checks network-free, and give them timeouts. See
[docs/tasks.md](docs/tasks.md).

## Pull requests

- Keep each pull request focused on one change.
- Add or update tests and documentation with the code.
- Add an entry under "Unreleased" in [CHANGELOG.md](CHANGELOG.md) for user-visible changes.
- Make sure `uv run pytest` and `uv run ruff check .` pass.

## Reporting security issues

Do not open a public issue. See [SECURITY.md](SECURITY.md).
