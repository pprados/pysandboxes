# PySandboxes wiki

Index of the documentation pages.

## Design and overview

- [Implementation](implementation.md) — how the framework is put together.
- [Roadmap](roadmap.md) — planned work and direction.
- [Releasing](release.md) — how a pre-release reaches test.pypi.org and Docker Hub (maintainers).
- [Use cases](use-cases.md) — agent skills, tools and MCP servers, AI coding agents, dependency updates, CI.
- [FAQ](faq.md) — common questions.
- [Alternatives](alternatives.md) — comparison with eighteen other sandboxes, frameworks and cloud services.
- [Configuration files](configuration.md) — where `.py-sandboxes` is looked up, `include`, and integration in a module.

## Security model

- [Weaknesses](weaknesses.md) — the known limits of the Python layer, stated plainly.
- [Security assessment of the Python layer](audit-python-security.md) — attacks and what stops them.
- [Security assessment of the eval-* guard](audit-eval-security.md) — attacks against dynamically evaluated code.
- [The transport unpickle guard](transport-unpickle-guard.md) — how the parent safely deserializes what the sandboxed child sends back.
- [Dynamically evaluated code](eval.md) — the `eval-*` rules.
- [Related CVEs](related-cves.md) — published vulnerabilities in agent frameworks.

## OS-level sandbox providers

- [Choosing a provider](os-providers.md) — what each technology enforces, and the paranoia levels.
- [Bubblewrap (bwrap)](bwrap.md)
- [Firejail](firejail.md)
- [Unshare](unshare.md)
- [QEMU](qemu.md)
- [LandLock](landlock.md)

## Networking and integration

- [DNS and iptables](dns.md) — name resolution and network filtering.
- [Database](database.md) — the data-table backend.
- [Integrating with the MCP SDK](mcp.md)

## Testing and samples

- [Test coverage map](tests.md) — what is exercised, where.
- [Samples](samples.md) — worked examples.

## Research

- [Confining Python by observation](../research/confining-python-by-observation.md) — the conceptual paper behind the design.
