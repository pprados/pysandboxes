# State schema

File: `.superpowers/architecture/ADR/adr-backfill-state.yml` (git-excluded, never committed). One analysis file per cluster in `.superpowers/architecture/ADR/adr-backfill-clusters/`.

```yaml
version: 1
repository: "git@github.com:org/repo.git"
started_at: "2026-01-15T10:30:00Z"
last_updated: "2026-01-15T14:22:00Z"

file_classification:
  # path -> {tier: int | null, category: string, override: bool}
  "pyproject.toml": {tier: 0, category: "dependency_manifest"}
  "pysandboxes/_os_sandbox.py": {tier: 2, category: "domain_structure"}
  "tests/unit_tests/test_architecture.py": {tier: 2, category: "layering_rules"}
  "tests/integration_tests/test_usage_with_providers.py": {tier: null, category: "test"}

commits:
  # sha -> annotation
  "abc123":
    pruned: false
    highest_tier: 0
    signals:
      - {type: "dependency_added", weight: 1.0, details: {package: "<name>"}}
    architectural_files: ["pyproject.toml"]
    processed: true
  "def456":
    pruned: true
    processed: true

clusters:
  # Commit-based cluster
  - id: 17
    title: "<Name of the decision>"
    commit_shas: ["abc123", "abc124", "abc125"]
    gap_commits: ["abc123a"]
    date_range: "2026-01-10 to 2026-01-12"
    confidence: 0.85
    status: "adr_generated"  # pending | analyzed | user_enriched | adr_generated | skipped
    analysis:
      intent_hypothesis: "..."
      solution_detected: "..."
    pr_metadata:
      number: 142
      title: "..."
      description: "..."
    user_context:
      problem: "..."
      alternatives: "..."
      rationale: "..."
      limitations: "..."
    adr_path: "<ADR directory>/0017-<slug>.md"

  # Document-derived cluster (supplementary ADR)
  - id: 18
    title: "<Name of the decision>"
    commit_shas: []  # empty for document-derived ADRs
    source: "wiki/<page>.md"
    date_range: "2026-01-08 to 2026-01-15"
    confidence: 0.9
    status: "adr_generated"
    adr_path: "<ADR directory>/0012-<slug>.md"

processing_cursor:
  step: "cluster_analysis"  # classification | pruning | filtering | clustering | gap_filling | cluster_analysis | gap_analysis | enrichment | ordering
  cluster_index: 17
  substep: "user_enrichment"

configuration:
  max_time_gap_days: 7
  adr_output_dir: ".superpowers/architecture/ADR"
  adr_format: "madr"  # madr | nygard | custom
  git_remote: "origin"
  pr_platform: "github"  # github | gitlab | bitbucket | none
```
