#!/usr/bin/env bash
# Scripted illustrative transcript. It does not run an AI agent or the shown project commands.
set -u

TYPE_DELAY="${TYPE_DELAY:-0.012}"
PAUSE="${PAUSE:-1.5}"
INTERACTION_PAUSE="${INTERACTION_PAUSE:-2}"
MODE="${1:-partial}"

type_out() {
  local text="$1" i
  text="${text//\\n/$'\n'}"
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

agent() {
  printf '\033[48;5;24;1;97magent: '
  type_out "$*"
  printf '\033[0m'
  sleep "${INTERACTION_PAUSE}"
}

human() {
  printf '\033[48;5;28;1;97mhuman: '
  type_out "$*"
  printf '\033[0m'
  sleep "${INTERACTION_PAUSE}"
}

run() {
  printf '    \033[48;5;236;1;97m$ '
  type_out "$*"
  printf '\033[0m'
  sleep "${PAUSE}"
}

result() {
  printf '    \033[48;5;238;37m'
  type_out "$*"
  printf '\033[0m'
  sleep "${PAUSE}"
}

clear
case "$MODE" in
  full)
    say "FULL MODE: pytest runs inside python-sb. Scripted example, not a live agent session."
    human "Create feature/markdown-export: fetch a URL, handle gzip, return Markdown; add main() for example.com and a gzip test."
    run "git switch -c feature/markdown-export"
    agent "Added fetch_page_as_markdown(url), main(example.com), a gzip unit test, and an HTTPS integration test against example.com."
    run "pytest -q"
    result "2 passed"
    run "python-sb --pysandboxes-config=.py-sandboxes.tests -m pytest -q"
    result "FAILED: python-import=test_web_to_markdown is missing"
    agent "Full mode separates runner rules with an empty-test baseline."
    run "python-sb --pysandboxes-config=.py-sandboxes.tests --learn=.py-sandboxes.learn -m pytest -q tests/test_pysandboxes_empty.py"
    result "1 passed; pytest and plugin candidates recorded"
    agent "With the empty-test baseline, I can now learn the permissions required by the tests."
    run "python-sb --pysandboxes-config=.py-sandboxes.tests --learn=.py-sandboxes.learn -m pytest -q"
    result "2 passed; candidates compared with empty-test baseline"
    agent "Reviewed the empty-test baseline: pytest imports and test discovery permissions belong in .py-sandboxes.tests."
    agent "Classified candidate and origins."
    agent "Promoted only the application imports and example.com network rule to .py-sandboxes"
    run "python-sb --pysandboxes-config=.py-sandboxes.tests -m pytest -q"
    result "2 passed"
    run "python-sb --pysandboxes-config=.py-sandboxes main.py"
    result "Example domain"
    human "Merge feature/markdown-export into main."
    agent "Review before merge:\n\nRules added to .py-sandboxes and their origins:\n\n  python-import=_markupbase,compression,gzip,html,io,os,re,struct,time,urllib,weakref,zlib\n    Used by fetch_page_as_markdown() through gzip decompression and HTML parsing.\n\n  python-import=web_to_markdown\n    Imported by main.py for main().\n\n  net=ALLOW|TCP|example.com|443|OUT\n    fetch_page_as_markdown() calls urllib.request.urlopen(); the marked integration test and main() exercise this path.\n\nDo you approve these rules and merge?"
    human "Yes, merge."
    run "git merge feature/markdown-export"
    ;;
  partial)
    say "PARTIAL MODE: pytest stays on the host; only @sandbox calls cross the boundary."
    human "Create feature/markdown-export: isolate the function in the sandbox; fetch a URL, handle gzip, return Markdown; add main() and an integration test that makes a real HTTPS call to example.com."
    run "git switch -c feature/markdown-export"
    agent "Added fetch_page_as_markdown(url) with @sandbox, main(example.com), gzip fixture test, and HTTPS smoke test."
    run "pytest -q"
    result "2 passed (host tests)"
    agent "I added @sandbox to the function as requested. Add sandbox_learn to its focused test, then run the test to check its permissions."
    run "pytest -q tests/test_web_to_markdown.py::test_fetch_page_as_markdown"
    result "FAILED inside @sandbox: application module/import permissions are missing"
    agent "The sandbox denied the call because its permissions are missing. I need to learn the required permissions from this focused test."
    run "SANDBOX_LEARN=1 pytest -p no:xdist -q tests/test_web_to_markdown.py::test_fetch_page_as_markdown"
    result "1 passed; candidates written to .py-sandboxes.learn"
    agent "Classified candidates and origins."
    agent "Promoted the justified application imports and example.com network rule to .py-sandboxes."
    run "pytest -p no:xdist -q tests/test_web_to_markdown.py::test_fetch_page_as_markdown"
    result "1 passed"
    human "Merge feature/markdown-export into main."
    agent "Review before merge:\n\nRules added to .py-sandboxes and their origins:\n\n  python-import=_markupbase,compression,gzip,html,io,os,re,struct,time,urllib,weakref,zlib\n    Used by fetch_page_as_markdown() through gzip decompression and HTML parsing.\n\n  python-import=web_to_markdown\n    Imported by main.py for main().\n\n  net=ALLOW|TCP|example.com|443|OUT\n    fetch_page_as_markdown() calls urllib.request.urlopen(); the marked integration test and main() exercise this path.\n\nDo you approve these rules and merge?"
    human "Yes, merge."
    run "git merge feature/markdown-export"
    ;;
  *)
    printf 'Usage: %s [full|partial]\n' "$0" >&2
    exit 2
    ;;
esac
