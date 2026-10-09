# Security policy

Security fixes are made for the latest release.

## Reporting

Report vulnerabilities privately through the repository's **Security** tab ("Report a
vulnerability"). Do not open a public issue. Include the agent-ab version, the operating
system, the impact, and steps or a minimal experiment that reproduce it.

## Scope

agent-ab runs agents you choose, on tasks you choose, with your permissions. It is not a
sandbox. See [docs/safety.md](docs/safety.md).

In scope:

- agent-ab reading, writing or deleting files outside the run directory, the workspace and
  the paths you configured (for example path traversal through `overlay`, `remove`, task
  ids or arm names);
- config or task values that make agent-ab run commands other than those configured (for
  example through placeholder expansion, shell quoting or Windows batch-file arguments);
- HTML reports that execute script from data in a run directory;
- secrets written by agent-ab beyond what the configuration and agent output contain;
- agent processes left running that agent-ab could reasonably have killed.

Out of scope:

- anything an agent does with the permissions it is given;
- task suites or configurations you chose to run;
- vulnerabilities in the agents themselves (report those to their maintainers);
- spend within the documented budget behaviour.
