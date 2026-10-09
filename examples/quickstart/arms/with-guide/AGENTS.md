# Working in this repository

## Before changing code
- Read the issue carefully and list every behaviour it asks for, including edge cases.
- Read the relevant modules and the existing tests before editing anything.
- Reproduce the problem first: a small script or a failing test that shows the bug.

## While changing code
- Keep the public API (names, signatures, return types) unless the issue asks otherwise.
- Make focused changes; do not reformat or refactor unrelated code.
- Prefer the standard library. Do not add dependencies.
- Code must behave the same on Windows, macOS and Linux: use `pathlib` or plain string
  handling, never assume a path separator or a shell.

## Before finishing
- Run the existing test suite: `python -m unittest discover -s tests -t .`
- Add or update tests that cover the requested behaviour and its edge cases.
- Re-read the issue and check each requirement against your change.
- Remove any scratch files you created.
