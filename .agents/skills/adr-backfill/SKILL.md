---
name: adr-backfill
description: Use when the pysandboxes repository lacks Architecture Decision Records for choices already made and the user wants them reconstructed from git history, `wiki/` and design documents (a new ADR for a past decision, an ADR audit, resuming an earlier backfill).
---

# ADR backfill

## Overview

Archaeology, not manufacturing: find the *decisions* buried in commits, `wiki/`, `CHANGELOG.md` and design documents, then surface them as ADRs. Not every commit is a decision. A dependency or a provider added, a guard removed, a layering rule, a default-deny trade-off: those are.

The user confirms every ADR. Never invent a rationale: if it is not in a commit, a PR or a document, ask.

## Where things live

- **ADR directory**: `.superpowers/architecture/ADR/`, with its `README.md` index. It sits under `.superpowers/`, which is git-excluded (`.git/info/exclude`): ADRs are never committed, and neither is the state. In a worktree, `.superpowers/` is absent: work in the main checkout.
- **Working state**: `.superpowers/architecture/ADR/adr-backfill-state.yml`, and one file per cluster in `.superpowers/architecture/ADR/adr-backfill-clusters/`. Persist state after every step so work survives the end of the conversation. At the start, look for an existing state and offer to resume or restart. Schema: `references/state-schema.md`.
- **ADR template**: `references/madr-template.md` (MADR, unless the user asks otherwise). Read the latest ADRs of the directory first and match their style and numbering.
- **Language**: ADRs are written in English, like the rest of the codebase.

## Process

1. **Classify files** and show the user the tier 0 and 1 classification to validate.
2. **Identify candidate commits**: structural changes to architectural files.
3. **Cluster** the commits into decisions.
4. **Fill gaps**: pull in minor commits (forgotten file, typo) that belong to a cluster.
5. **For each cluster**: analyze the intent, ask the user for context, generate the ADR.
6. **Scan complementary sources** for decisions no commit carries.
7. **Enrich** the ADRs with cross-references, diagrams, tables.
8. **Order chronologically** and renumber.
9. **Update the ADR index** of the ADR directory, if it has one.

Start with the high-confidence clusters (tier 0 and 1), get feedback, calibrate, then continue.

## 1. File classification

Consider present and deleted files: a deletion can be the decision.

| Tier | What | In this repository |
|------|------|--------------------|
| 0 | Dependency manifests, highest signal | `pyproject.toml` (an extra added or removed is a technology choice) |
| 1 | Infrastructure, build, CI | `.github/workflows/`, `Dockerfile-*`, `Makefile`, `scripts/` |
| 2 | Domain structure, entry points | `pysandboxes/_os_sandbox.py` (provider registry), `pysandboxes/guard_*.py`, `pysandboxes/eval_*.py`, `pysandboxes/remote/`, `pysandboxes/sandboxes_api.py`, `pysandboxes/py_sandbox.py`, import-layering rules in `tests/unit_tests/test_architecture.py` |
| 3 | Interface contracts | the `.py-sandboxes` rule grammar and its keys, the `python-sb` CLI, the public API |

Supportive, usually not decisions: other tests, `samples/`, generated files, `uv.lock` on its own.

Decision artifacts, checked separately: `wiki/` (`weaknesses.md`, `audit-*.md`, `roadmap.md`, one page per provider), `CHANGELOG.md`, `research/*.md`, `.superpowers/specs/`.

Doubt: "If this changed significantly, would a senior engineer want to know *why* before approving?" Yes means architectural.

## 2. Structural change signals

New directory or module, file renamed or moved across a boundary, dependency added, removed or major-bumped, new entry point or provider, CI pipeline added or reshaped, new base class others inherit, rule-schema change (not just values), a guard or provider removed, an import-layering rule changed. A one-line extra in `pyproject.toml` outweighs a 200-line refactor of a helper.

## 3. Clustering

A cluster is ONE decision, even over several commits, related by intent and not only by proximity, usually days to two weeks, and nameable in a sentence ("the landlock provider", "removing the pickle guard").

Break a cluster on a gap of more than one or two weeks with a context switch, on another author in an unrelated area, or on markers (`BREAKING`, `migrate to`, `rewrite`). Avoid over-clustering ("all of the remote layer"), under-clustering (one commit per cluster) and mixing two decisions.

Number the candidates in strict chronological order (earliest commit first). Present them by confidence tier, ascending within a tier. The dates of this history may have been replayed or rewritten: confirm the order with the user before numbering.

## 4. Gates: when to stop and ask

Always ask before generating an ADR: present the analysis, let the user confirm or correct. Ask on:

- **classification doubt**: "Is `remote/slirp4netns_common.py` architectural or a helper?";
- **cluster boundaries**: "Commits abc123..def456 span three weeks and touch a guard and a provider. One decision or two?";
- **unclear intent**: "This cluster adds a dependency, but I cannot tell what drove it.";
- **low confidence**: "Four commits adjust logging. ADR-worthy or housekeeping?".

Before each ADR, gather: the **trigger** (the problem or constraint), the **alternatives** considered, the **rationale**, the **trade-offs accepted** (known limits, risks, debt), and the **related decisions** (supersedes or depends on). If a PR description or commit message already says it, confirm instead of re-asking.

## 5. Complementary sources

Commits are primary, not exclusive.

- **Design documents** (`wiki/`, `research/`, `.superpowers/specs/`) can document a decision before any code. When one describes a decision, note it as an ADR source, cross-reference the commits that implemented it, and use it for "Considered Options" and "Rationale". Cite the file as the source of the ADR.
- **Docs and `CHANGELOG.md`** enrich commit-based ADRs with diagrams, tables, and integration points.

After the commit-based ADRs, read all of them, then show the user the decisions not yet captured: "I found N decisions in the wiki and specs that no ADR covers: ... Which should become ADRs?"

## 6. Enrichment

- Build the reference graph: which ADRs depend on, supersede, or ship with others. Cite them explicitly ("With the provider registry in place (ADR-0003)...").
- Put diagrams, tables and workflows from related documents inline in the ADR, not only as links.
- If the user describes how the work was done (collaboration pattern, choices made on the way, debt found afterwards), record it in an "Implementation Notes" section.

## 7. Chronological ordering

ADRs are numbered by decision date, not by generation order. Criteria, in order: earliest commit of the cluster, creation date of the source document (`git log`), logical dependency (the dependency first).

When added ADRs fall between existing ones, show the old-to-new mapping and get approval. Then rename with `git mv` in two passes to avoid collisions (all changing files to `temp-*`, then to their final names), and update titles, cross-references (`ADR-0005` to `ADR-0008`), the index, and the state file.

## 8. Output

MADR, with a footer saying what the ADR is reconstructed from:

- commit-based: `*Reconstructed from commits {first_sha}..{last_sha} ({date_range})*`
- document-based: `*Reconstructed from {source_file} ({date_range})*`

The index (a table: linked title, one-sentence outcome, sorted ascending) is updated after every addition, renumbering or removal.

## Quality bar

A good backfilled ADR could have been written at the time, captures *why* and not only *what*, stands alone, says honestly what is reconstructed and what the user confirmed, and cross-references its neighbors.

A bad one describes the code changes, invents a rationale, combines unrelated decisions, documents a symptom instead of the choice, or ignores the documents.

## Anti-patterns

- **Invented rationale**: ask.
- **Over-automation**: user judgment is essential.
- **Treating all commits equally**: a dependency addition is almost always a decision, a whitespace fix never is.
- **Ignoring `wiki/` and design documents**.
- **Skipping enrichment**: a bare ADR is worth less than one with diagrams and cross-references.
- **Committing an ADR or the state**: both stay under the git-excluded `.superpowers/`.

## Resources

- `references/state-schema.md`: the `state.yml` schema and the processing cursor.
- `references/madr-template.md`: the ADR template.
