---
applyTo: 'Python files named guard_*.py in pysandboxes/.'
---
## Standard: Guard Module Pattern

Standardize guard_*.py security modules in pysandboxes/ to implement parse_rules()/patch_rules(learn: bool) interfaces using immutable NamedTuple rule classes and Learn* learning-mode variants to ensure consistent sandbox security enforcement and safe violation auditing. :
* Define rule data structures as NamedTuple classes to ensure immutability and clear field definitions
* Implement parse_rules() function that accepts configuration lines and an errors list, returning parsed rule structures
* Implement patch_rules(learn: bool) -> dict[str, Callable] function returning monkey-patches for security enforcement
* Support learning mode with dedicated Learn* rule classes that record violations instead of blocking them

Full standard is available here for further request: [Guard Module Pattern](../../.packmind/standards/guard-module-pattern.md)