# Security policy

## Supported versions

Security fixes are made for the latest released version.

## Reporting a vulnerability

Please report vulnerabilities privately through the repository's **Security** tab
("Report a vulnerability"), which opens a private GitHub security advisory. Do not open a
public issue for a security problem.

Include:

- the agent-ab version and operating system;
- a description of the problem and its impact;
- steps or a minimal experiment that reproduces it.

You should receive an acknowledgement within a week. Please allow time for a fix before
disclosing the issue publicly.

## Threat model

agent-ab is a harness for running coding agents that you choose, on tasks that you choose,
with your permissions. It is **not a sandbox**, and it does not try to contain the agents it
launches. See [docs/safety.md](docs/safety.md).

In scope (please report):

- agent-ab itself writing, deleting or reading files outside the run directory, the
  workspace root and the paths you configured, for example through path traversal in
  `overlay`, `remove`, task ids or arm names;
- configuration or task values that cause agent-ab to execute commands other than those the
  configuration specifies (for example through placeholder expansion or shell quoting);
- HTML reports that execute script content from task ids, arm names, agent output or other
  data in a run directory;
- secrets written to the run directory or reports by agent-ab beyond what the configuration
  and agent output contain;
- failures to kill an agent's process tree on timeout or cancellation that agent-ab could
  reasonably prevent.

Out of scope:

- anything an agent does with the permissions it is given: reading your home directory,
  using your credentials, accessing the network, reading hidden checks;
- malicious task suites or configurations that you chose to run (they run with your
  permissions by design);
- vulnerabilities in the agents themselves (report those to their maintainers);
- cost overruns within the documented budget behaviour.

Run experiments inside a container or VM with only the credentials the agent needs.
