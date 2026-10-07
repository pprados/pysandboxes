# Security Policy

PySandboxes exists to run code its caller does not trust. A hole in it is not
a bug among others, so this page says where to send one, what counts as one,
and what does not.

## Reporting a vulnerability

Report privately, never in a public issue or pull request:

- **Preferred**: a [GitHub security advisory](https://github.com/pprados/pysandboxes/security/advisories/new)
  on this repository.
- **Alternative**: `github[at]prados.fr`.

Please include the provider in use (`none`, `subprocess`, `landlock`, `bwrap`,
`firejail`, `unshare`, `qemu`), the `.py-sandboxes` rules in force, the Python
and kernel versions, and a proof of concept small enough to run. A report
naming the layer it defeats is worth far more than one that only shows an
outcome.

You will get an acknowledgement within 7 days and an assessment within 30. If
a fix is warranted, the advisory is published with the release that carries
it, and the reporter is credited unless they ask otherwise. Please hold public
disclosure until then.

## What counts as a vulnerability

The project claims two layers. Anything that defeats one of them while the
other is configured to hold is in scope:

- sandboxed code that reads, writes or deletes a path no rule allows;
- a network connection to an address no rule allows, including through a DNS
  answer the pinning should have refused;
- an import or a call to a guarded API that the rules deny, including through
  `eval`, `exec`, `compile` or a deserialisation such as `pickle`;
- escaping the OS boundary of a provider: leaving the namespace, reaching the
  host filesystem, or the guest reaching the host under `qemu`;
- an `eval-*` budget or timeout that cannot be enforced, leaving the host
  process stuck or exhausted;
- a rule file, learning-mode output or configuration path that lets sandboxed
  code widen its own permissions.

## What does not count

These are documented positions, not oversights. Reporting them is welcome as
an issue, but they are not treated as vulnerabilities:

- **Known Python-layer weaknesses**, listed in [`wiki/weaknesses.md`](wiki/weaknesses.md).
  The Python layer is friction against accidental damage; the OS layer is the
  boundary. Undoing a monkey patch from inside the interpreter is expected.
- **`py-sandbox=False`**, which switches the Python layer off on purpose. Only
  the chosen provider's OS boundary remains.
- **`none` and `subprocess`**, which provide no OS boundary by design.
- **What a given technology cannot express**, as documented per provider in the
  README table — for example `landlock` denies a path but cannot hide it.
- **Attacks already published** in [`wiki/audit-eval-security.md`](wiki/audit-eval-security.md)
  and [`wiki/audit-python-security.md`](wiki/audit-python-security.md), unless
  you defeat the mitigation described there.
- Rules that grant more than their author intended: a permissive
  `.py-sandboxes` is a configuration mistake, not a defect.

## Supported versions

Fixes land on `develop` and ship in the next release. Older releases are not
back-patched: the project has not reached a version that promises it.

## Scope

This repository only: the `pysandboxes` package, its providers and its rule
files. The sample applications under `samples/` are deliberately vulnerable
demonstrations — their flaws are the point, and they are out of scope.
