# PySandboxes documentation

PySandboxes runs Python under a deny-by-default policy stored in `.py-sandboxes`. On Linux, an OS provider can add a kernel boundary. Choose a reading path below.

## Reading paths

**Overview (5 minutes)**

1. [README](../README.md): the demo, the quick start, the limits at a glance.
2. [Use cases](use-cases.md): which scenario, which protection level.

**Try it (30 minutes)**

1. Run the [quick demo](../samples/quick-demo/README.md): learn a policy, then see it refuse an attack.
2. [Usage](usage.md): complete mode or partial mode.
3. [Configuration files](configuration.md): read and lock a `.py-sandboxes`.
4. [Provider comparison](os-providers.md): choose the OS layer.
5. [Alternatives](alternatives.md): how it compares with containers, microVMs and hosted services.

**Security review**

1. [Security model](security-model.md): the layers and the filters.
2. [Weaknesses](weaknesses.md): known limits and residual risks.
3. [Python-layer assessment](audit-python-security.md) and [`eval-*` assessment](audit-eval-security.md): attack by attack.
4. [Test coverage map](tests.md): what is exercised, and what is not.
5. [SECURITY.md](../SECURITY.md): what counts as a vulnerability, and how to report one.

## Get started and configure

- [README](../README.md): run an application in complete mode, with the limits at a glance.
- [Usage](usage.md): complete mode, partial mode, `@sandbox`, `init_fn`, learning.
- [Configuration files](configuration.md): locate `.py-sandboxes`, compose files with `include`, and configure a module.
- [FAQ](faq.md): answers to common usage and troubleshooting questions.
- [Samples](samples.md): framework integrations and instructions for running the sample projects.
- [Integrating with the MCP SDK](mcp.md): configure a sandbox for an MCP server.
- [Database](database.md): use the database-backed data table.

## Understand the security model

- [Security model](security-model.md): why, the layers, the risks addressed and the filters.
- [Weaknesses](weaknesses.md): known limits and residual risks of the Python layer.
- [Security assessment of the Python layer](audit-python-security.md): attacks, mechanisms, regression tests, and open paths.
- [Security assessment of dynamically evaluated code](audit-eval-security.md): the `eval-*` guard's behavior and limits.
- [Dynamically evaluated code](eval.md): configuration reference for the `eval-*` rules.
- [Transport unpickle guard](transport-unpickle-guard.md): validation of objects received from the sandbox child.
- [Native guard study](audit-native-guard-study.md): the native-extension approach considered and the decision made.
- [Related CVEs](related-cves.md): published vulnerabilities in adjacent agent frameworks.

## Choose and operate an OS provider

- [Provider comparison](os-providers.md): which provider for which situation, enforcement mechanisms, prerequisites, compatibility, and trade-offs.
- [Landlock](landlock.md)
- [Bubblewrap (`bwrap`)](bwrap.md)
- [Firejail](firejail.md)
- [Unshare](unshare.md)
- [QEMU](qemu.md)
- [DNS and network filtering](dns.md): DNS resolution and `iptables` behavior.
- [Docker Hub images](docker-hub.md): pull and run published provider images.

## Compare and evaluate

- [Alternative sandboxes](alternatives.md): comparison with other sandboxes, frameworks, and hosted services.
- [Use cases](use-cases.md): threat scenarios and suitable isolation levels.
- [Test coverage map](tests.md): test suites, provider matrix, skipped scenarios, and approximate counts.
- [Learning from tests](learning-from-tests.md): use full or partial test runs to discover and review sandbox permissions.

## Maintain and explore the project

- [Implementation](implementation.md): framework architecture and execution flow.
- [Coding-agent skills and plugin](coding-agents.md): learn and review rules from tests with a human approval gate.
- [Roadmap](roadmap.md): planned work and project direction.
- [Releasing](release.md): release and publication process for maintainers.
- [Confining Python by observation](../research/confining-python-by-observation.md): research background for the policy-learning approach.
