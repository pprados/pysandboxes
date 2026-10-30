# MADR template

```markdown
# [seq id] - [title]

## Context and Problem Statement

...

## Considered Options

1. [option name] - [description]
2. [option name] - [description]

## Decision Outcome

Chose **Option N**: ...

### Architecture

[diagrams, tables, module descriptions from enrichment]

### Rationale

...

### Implementation Notes

[collaboration patterns, technical decisions, debt identified: only when the user provides them]

### Consequences

**Positive:**
- ...

**Limitations accepted:**
- ...

---
*Reconstructed from commits {first_sha}..{last_sha} ({date_range})*
```

For an ADR derived from a document, end with `*Reconstructed from {source_file} ({date_range})*`.
