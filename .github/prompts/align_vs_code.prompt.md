---
agent: 'agent'
model: 'claude sonet 2'
tools: ['edit', 'search']
description: 'Align debugging and tool parameters between PyCharm and VSCode configurations'
---

# Objective
Align debugging and tool parameters between PyCharm and VSCode configurations

Generate a unified configuration that aligns debugging and tool parameters between PyCharm (.idea) and VSCode (launch.json and settings.json).

## Task
1. **Extract PyCharm Configuration**
  - Parse `.idea/runConfigurations/*.xml` files
  - Extract run/debug launcher parameters (Python interpreter, script path, arguments, environment variables)
  - Identify PyCharm-specific tool settings

2. **Extract VSCode Configuration**
  - Parse existing `.vscode/launch.json`
  - Parse existing `.vscode/settings.json`

3. **Extract Tool Configuration**
  - Parse `Makefile` for tool commands and parameters
  - Extract pytest, black, mypy, flake8, or other linter configurations
  - Identify common build/test targets

4. **Generate Alignment Report**
  - Map PyCharm launchers to VSCode debug configurations
  - Identify parameter differences and conflicts
  - List tool parameter discrepancies

5. **Output**
  - Generate updated `.vscode/launch.json` with PyCharm-aligned configurations
  - Generate updated `.vscode/settings.json` with tool parameter alignment
  - Provide migration guide for inconsistencies

## Format
- Use JSON for VSCode configurations
- Include comments explaining parameter mappings
- Highlight any manual adjustments needed
- generate reports/align_report.md