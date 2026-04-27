# Project Structure – pysandboxes

**Date:** 2026-03-12  
**Repository type:** Monolith  
**Primary part:** pysandboxes (backend/library/CLI)

## Directory layout (high level)

- pysandboxes/ – Main package (sandbox runtime, guards, daemons, API)
- tests/ – Unit, integration, container tests
- samples/ – Sample consumers (mcp-client-demo, mcp-server-demo)
- _bmad/ – BMAD method config and workflows
- pyproject.toml, Makefile, README.md

## Classification

- **Monolith:** Single cohesive codebase; main deliverable is the pysandboxes package.
- **Part:** main (root); project_type_id: backend.
