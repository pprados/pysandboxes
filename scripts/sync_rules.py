#!/usr/bin/env python3
"""Sync skills and rules from .ai/ to plugin directories (.claude, .cursor, .opencode)."""

import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
AI_DIR = PROJECT_ROOT / ".ai"
PLUGIN_DIRS = {
    "claude": PROJECT_ROOT / ".claude",
    "cursor": PROJECT_ROOT / ".cursor",
    "opencode": PROJECT_ROOT / ".opencode",
}


def sync_skills():
    """Symlink .ai/skills to all plugin dirs."""
    skills_src = AI_DIR / "skills"
    if not skills_src.exists():
        print(f"⚠ Skills dir not found: {skills_src}")
        return

    for editor, plugin_dir in PLUGIN_DIRS.items():
        skills_link = plugin_dir / "skills"
        plugin_dir.mkdir(parents=True, exist_ok=True)

        if skills_link.exists() or skills_link.is_symlink():
            skills_link.unlink()

        # Create relative symlink
        rel_path = os.path.relpath(skills_src, plugin_dir)
        skills_link.symlink_to(rel_path)
        print(f"✓ {editor}: skills → {rel_path}")


def sync_rules():
    """Sync rules: .md symlinks for Claude, symlinks for others."""
    rules_src = AI_DIR / "rules"
    if not rules_src.exists():
        print(f"⚠ Rules dir not found: {rules_src}")
        return

    # Claude: symlink .mdc files as .md
    claude_rules = PLUGIN_DIRS["claude"] / "rules"
    claude_rules.mkdir(parents=True, exist_ok=True)

    for mdc_file in rules_src.rglob("*.mdc"):
        # Skip templates and nested structure artifacts
        if ".template." in mdc_file.name:
            continue

        rel_path = mdc_file.relative_to(rules_src)

        # Skip if nested under subdirs like .ai, .claude, etc
        if rel_path.parts[0].startswith("."):
            continue

        md_file = claude_rules / rel_path.with_suffix(".md")
        md_file.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing link/file
        if md_file.exists() or md_file.is_symlink():
            md_file.unlink()

        # Symlink to .mdc file with .md extension
        rel_to_source = os.path.relpath(mdc_file, md_file.parent)
        md_file.symlink_to(rel_to_source)
        print(f"✓ claude: {md_file.relative_to(claude_rules)} → {rel_to_source}")

    # Cursor & OpenCode: symlink to .ai/rules
    for editor in ["cursor", "opencode"]:
        rules_link = PLUGIN_DIRS[editor] / "rules"
        if rules_link.exists() or rules_link.is_symlink():
            if rules_link.is_dir() and not rules_link.is_symlink():
                shutil.rmtree(rules_link)
            else:
                rules_link.unlink()

        rel_path = os.path.relpath(rules_src, PLUGIN_DIRS[editor])
        rules_link.symlink_to(rel_path)
        print(f"✓ {editor}: rules → {rel_path}")


def main():
    os.chdir(PROJECT_ROOT)
    print(f"Syncing from {AI_DIR}\n")

    sync_skills()
    print()
    sync_rules()

    print("\n✓ Sync complete")


if __name__ == "__main__":
    main()
