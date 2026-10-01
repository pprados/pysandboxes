#!/usr/bin/env bash
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Play the quick demo unattended, up to its first `--evil`, for a recording: `make` records it and
# rebuilds ../quick-demo.gif, `make rehearse` plays it at full speed.
# Each step prints a comment, types its command, runs it and waits. TYPE_DELAY and PAUSE set the pace.
# The script re-runs itself under bwrap, where /home is a tmpfs holding only the caller's home and an empty
# /home/pysandboxes. HOME points to the latter, so the refused `--dir ~` shows no real user name.
set -u
if [[ -z ${DEMO_NAMESPACE:-} ]]; then
  export DEMO_NAMESPACE=1
  exec bwrap --dev-bind / / --tmpfs /home --bind "${HOME}" "${HOME}" --dir /home/pysandboxes \
    --chdir "${PWD}" "$(realpath "$0")" "$@"
fi
TYPE_DELAY="${TYPE_DELAY:-0.03}"
PAUSE="${PAUSE:-4}"

shopt -s expand_aliases
source "$(dirname "${BASH_SOURCE[0]}")/../init.sh"
HOME=/home/pysandboxes

type_out() {
  local text="$1" i
  for ((i = 0; i < ${#text}; i++)); do
    printf '%s' "${text:i:1}"
    sleep "${TYPE_DELAY}"
  done
  printf '\n'
}

say() {
  printf '\n\033[1;33m'
  type_out "# $*"
  printf '\033[0m'
}

run() {
  printf '\033[1;32m$\033[0m '
  type_out "$*"
  eval "$@"
  sleep "${PAUSE}"
}

clear
say "An ordinary script: fetch a URL, read a directory, read \$DEMO_API_KEY."
say "Nothing tells us what it may touch, and nothing stops it."
run python app/demo.py --url=https://example.com --dir=data/

say "No policy yet. Put python-sb in front of python: it learns what the script really does."
run "ls -a .py-sandboxes*"
run python-sb --learn app/demo.py --url=https://example.com --dir=data/

say "What was learned, on top of the defaults: one variable, one host, two read-only directories."
run "grep -E '^(net|expose-ro|expose-rw|python-api|env=DEMO)' .py-sandboxes"
say "A secret is set in this shell, but the application never read it: it is not in the policy."
run "echo \$AWS_SECRET_ACCESS_KEY"
run "grep -c AWS_SECRET_ACCESS_KEY .py-sandboxes"

say "Replay in the learned context: the policy is enforced, and legitimate use still works."
run python-sb app/demo.py --url=https://example.com --dir=data/

say "Same code, another context: this site and this directory were never learned."
run python-sb app/demo.py --url https://www.wikipedia.org --dir '~'

say "Learned once, reviewed like code, and whatever was not learned is refused."
say "pysandboxes: https://github.com/pprados/pysandboxes"
