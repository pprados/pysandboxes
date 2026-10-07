# Security limits and residual risks

## Scope

The Python layer (`py-sandbox`) intercepts supported Python APIs. It is a policy
and visibility layer, not an isolation boundary against a determined attacker.
Use an OS provider when the threat model includes hostile code that can use
native extensions or direct system calls. The provider comparison describes
what each OS mechanism can enforce and its prerequisites.

## Python-layer limits

- **Introspection can reach guard internals.** Python code can inspect wrappers,
  original callables, rules, or the armed state. The
  [Python-layer assessment](audit-python-security.md) separates demonstrated
  paths from source-based reasoning and links each finding to regression tests.
- **Native code can bypass Python wrappers.** `ctypes`, compiled extensions,
  and direct system calls can access capabilities the Python layer does not
  mediate. Secrets already present in the process memory are not protected from
  such code.
- **Some API edge cases remain.** For example, `dir_fd` checks resolve a path
  before the kernel operation; a concurrent rename can create a
  time-of-check/time-of-use race. A file descriptor already held by the code is
  itself a capability.
- **The local transport is not an OS boundary.** A co-resident process that
  learns the daemon's local port and token may reach it. The token and random
  port raise the cost; they do not protect against an attacker who can read
  them.

## Return-value deserialization

The trusted parent must deserialize values returned by the sandbox child. The
default `remote-result-mode=data-only` accepts values only: primitive values,
built-in containers, paths, dates and time zones, decimals, fractions, UUIDs
and IP addresses, from a closed list. It
rejects applications that return custom objects. `remote-result-mode=objects`
rebuilds them behind a guard that filters known dangerous pickle gadgets, but it
is a fail-open denylist and does not prove that every gadget is blocked. See the [transport guard assessment](transport-unpickle-guard.md)
for the result and exception channel behavior.

## Additional measured findings

The development assessment also records narrower cases: `ctypes.pythonapi` is
created before the constructor patch can intercept it; a private event-loop
`KeyboardInterrupt` path can call `_thread.interrupt_main`; and enforcement can
be disarmed through the same introspection weakness. These are detailed in the
[Python-layer assessment](audit-python-security.md) and are not claims that an
OS provider is bypassed.

## Recommendations

- Keep the Python layer enabled for policy feedback and supported-API checks.
- Add an OS provider appropriate to the deployment when native or compiled code
  is within the threat model. Review its host, kernel, network, and container
  prerequisites before relying on it.
- Treat learned rules as a starting policy. Exercise representative paths and
  review the result before enforcing it.
- Keep the default `remote-result-mode=data-only` when the application can
  return values; set `remote-result-mode=objects` only for the objects it must
  return, and keep `remote-result-guard` on.
