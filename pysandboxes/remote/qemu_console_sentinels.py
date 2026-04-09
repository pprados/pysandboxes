# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Sentinel strings for QEMU console filter (host shows only guest Python output).

The guest prints PYTHON_OUTPUT_START just before running the user script
and PYTHON_OUTPUT_END just after. The host filter forwards only lines between them.
"""

# Emitted by guest to stderr just before launching the user Python script
PYTHON_OUTPUT_START = "[PYSANDBOXES]PYTHON_OUTPUT_START"
# Emitted by guest to stderr just after the user Python script exits
PYTHON_OUTPUT_END = "[PYSANDBOXES]PYTHON_OUTPUT_END"
