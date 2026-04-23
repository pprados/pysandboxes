#!/usr/bin/env bash
# Minimal validation for a sample under samples/<target>/.
# Usage: from repo root,  ./samples/test.sh langchain-demo
#    or:  cd samples && ./test.sh crewai-demo
#    or:  ./samples/test.sh mcp-client-demo | mcp-server-demo
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:?usage: $0 <sample-directory> (e.g. langchain-demo, mcp-client-demo, mcp-server-demo)}"
cd "${SCRIPT_DIR}/${TARGET}"
make init
make validate
