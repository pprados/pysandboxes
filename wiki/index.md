# PySandboxes wiki

Index of the documentation pages.

## Design and overview

- [Implementation](implementation.md) — how the framework is put together.
- [Roadmap](roadmap.md) — planned work and direction.
- [FAQ](faq.md) — common questions.

## Security model

- [Weaknesses](weaknesses.md) — the known limits of the Python layer, stated plainly.
- [Security assessment of the Python layer](audit-python-security.md) — attacks and what stops them.
- [Security assessment of the eval-* guard](audit-eval-security.md) — attacks against dynamically evaluated code.
- [The transport unpickle guard](transport-unpickle-guard.md) — how the parent safely deserializes what the sandboxed child sends back.
- [Dynamically evaluated code](eval.md) — the `eval-*` rules.

## OS-level sandbox providers

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

- [Confining Python by observation](research_fr.md) — the conceptual paper behind the design (French).
