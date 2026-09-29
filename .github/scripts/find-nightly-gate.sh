#!/usr/bin/env bash
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Job reuse-lookup of release.yml. Usage: find-nightly-gate.sh <commit sha>
# Looks for a completed nightly (schedule) run of full-gate.yml on develop at that commit whose suite jobs all
# succeeded. A nightly with nothing new to test still concludes success with its suites skipped, so the jobs are
# read, not the run's conclusion. A workflow_dispatch run never counts.
# Prints reuse=true and run=<url>, or reuse=false, for $GITHUB_OUTPUT.
set -euo pipefail

sha=$1
runs=$(gh run list --workflow full-gate.yml --event schedule --branch develop --commit "$sha" --status completed \
    --limit 100 --json databaseId,url,headSha,event,status)
# shellcheck disable=SC2016  # $sha is a jq variable, bound by --arg
nightly='.[] | select(.headSha == $sha and .event == "schedule" and .status == "completed") | .databaseId'
for id in $(jq -r --arg sha "$sha" "$nightly" <<<"$runs"); do
    jobs=$(gh api --paginate "repos/$GH_REPO/actions/runs/$id/jobs?per_page=100")
    if jq -se '[.[].jobs[]] as $jobs | all("integration", "samples", "containers"; . as $suite
            | [$jobs[] | select(.name | startswith($suite + " / "))] | length > 0 and all(.conclusion == "success"))' \
            <<<"$jobs" >/dev/null; then
        echo "reuse=true"
        jq -r --argjson id "$id" '.[] | select(.databaseId == $id) | "run=\(.url)"' <<<"$runs"
        exit 0
    fi
done
echo "reuse=false"
