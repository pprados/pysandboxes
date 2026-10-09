# PySandboxes documentation

This index is organized around common reader tasks. Start with a working
example, understand the security model and its limits, then select a provider
and verify the scenarios your application needs.

## Get started and configure

- [Quick start and use cases](../README.md) — run an application in complete mode and follow links to partial mode.
- [Configuration files](configuration.md) — locate `.py-sandboxes`, compose files with `include`, and configure a module.
- [FAQ](faq.md) — answers to common usage and troubleshooting questions.
- [Samples](samples.md) — framework integrations and instructions for running the sample projects.
- [Integrating with the MCP SDK](mcp.md) — configure a sandbox for an MCP server.
- [Database](database.md) — use the database-backed data table.

## Understand the security model

- [Weaknesses](weaknesses.md) — known limits and residual risks of the Python layer.
- [Security assessment of the Python layer](audit-python-security.md) — attacks, mechanisms, regression tests, and open paths.
- [Security assessment of dynamically evaluated code](audit-eval-security.md) — the `eval-*` guard's behavior and limits.
- [Dynamically evaluated code](eval.md) — configuration reference for the `eval-*` rules.
- [Transport unpickle guard](transport-unpickle-guard.md) — validation of objects received from the sandbox child.
- [Native guard study](audit-native-guard-study.md) — the native-extension approach considered and the decision made.
- [Related CVEs](related-cves.md) — published vulnerabilities in adjacent agent frameworks.

## Choose and operate an OS provider

- [Provider comparison](os-providers.md) — enforcement mechanisms, prerequisites, compatibility, and trade-offs.
- [Landlock](landlock.md)
- [Bubblewrap (`bwrap`)](bwrap.md)
- [Firejail](firejail.md)
- [Unshare](unshare.md)
- [QEMU](qemu.md)
- [DNS and network filtering](dns.md) — DNS resolution and `iptables` behavior.
- [Docker Hub images](docker-hub.md) — pull and run published provider images.

## Test and evaluate

- [Test coverage map](tests.md) — test suites, provider matrix, skipped scenarios, and approximate counts.
- [Alternative sandboxes](alternatives.md) — comparison with other sandboxes, frameworks, and hosted services.
- [Use cases](use-cases.md) — threat scenarios and suitable isolation levels.

## Maintain and explore the project

- [Implementation](implementation.md) — framework architecture and execution flow.
- [Coding-agent skills and plugin](coding-agents.md) — learn and review rules from tests with a human approval gate.
- [Roadmap](roadmap.md) — planned work and project direction.
- [Releasing](release.md) — release and publication process for maintainers.
- [Confining Python by observation](../research/confining-python-by-observation.md) — research background for the policy-learning approach.
