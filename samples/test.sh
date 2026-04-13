#!/usr/bin/env bash
# Minimal validation for a sample under samples/<target>/.
# Usage: from repo root,  ./samples/test.sh langchain-demo
#    or:  cd samples && ./test.sh crewai-demo
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:?usage: $0 <sample-directory> (e.g. langchain-demo)}"
cd "${SCRIPT_DIR}/${TARGET}"
make init
make validate
