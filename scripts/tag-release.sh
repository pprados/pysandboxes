#!/usr/bin/env bash
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Behind make publish-pre-release, publish-patch and publish-minor. Usage:
#   tag-release.sh pre <X.Y.Z(a|b|rc)N> | tag-release.sh patch | tag-release.sh minor
# Tags the head of develop with a signed vX.Y.Z… and pushes develop, then the tag: release.yml verifies and publishes
# it. A final version is the last final tag reachable from HEAD (v0.0.0 without one) bumped; it dates the CHANGELOG.md
# entry [0.0.0] before the tag and opens a new one after, so the open entry never reaches master. After the first
# final version, changelog-draft.sh drafts what changed below the hand-written note of that entry; the maintainer
# edits it ($VISUAL, $EDITOR, else vi, when on a terminal) and approves it with the tag. A published tag is never moved.
set -euo pipefail

die() {
    echo "$*" >&2
    exit 1
}

open_entry='## [0.0.0] - 202X-XX-XX'
mode=${1:-}
case $mode in
pre)
    version=${2:-}
    [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+(a|b|rc)[0-9]+$ ]] ||
        die "Usage: make publish-pre-release VERSION=X.Y.Z(a|b|rc)N, e.g. VERSION=0.1.0b2"
    ;;
patch | minor)
    last=$(git tag --merged HEAD -l 'v*' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n 1 || true)
    IFS=. read -r major minor patch <<<"${last:-v0.0.0}"
    major=${major#v}
    if [[ $mode == patch ]]; then
        version=$major.$minor.$((patch + 1))
    else
        version=$major.$((minor + 1)).0
    fi
    [[ $(grep -cxF "$open_entry" CHANGELOG.md || true) == 1 ]] ||
        die "CHANGELOG.md must have exactly one '$open_entry' entry to date."
    ;;
*)
    die "Usage: tag-release.sh pre <X.Y.Z(a|b|rc)N> | tag-release.sh patch | tag-release.sh minor"
    ;;
esac
tag=v$version

git diff-index --quiet HEAD -- || die "Git working directory is not clean. Please commit or stash your changes."
[[ $(git rev-parse --abbrev-ref HEAD) == develop ]] || die "You must be on the 'develop' branch to publish a release."
git fetch --quiet --tags origin develop
git merge-base --is-ancestor origin/develop HEAD ||
    die "develop is behind or has diverged from origin/develop: pull first."
if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    die "Tag $tag already exists."
fi

previous=$(git describe --tags --abbrev=0 --match 'v[0-9]*' 2>/dev/null || true)
echo "Changes since ${previous:-the first commit} that reach the pipeline or the wheel:"
git --no-pager diff --stat "${previous:-$(git hash-object -t tree /dev/null)}" HEAD -- \
    .github Makefile pyproject.toml uv.lock pysandboxes
if [[ $mode != pre && -n $last ]]; then
    draft=$("$(dirname "$0")/changelog-draft.sh" "$last")
    if [[ -n $draft ]]; then
        DRAFT=$draft awk -v entry="$open_entry" '
            $0 == entry { print; inside = 1; next }
            inside && /^## \[/ { print ENVIRON["DRAFT"]; print ""; inside = 0 }
            { print }
            END { if (inside) print ENVIRON["DRAFT"] }' CHANGELOG.md >CHANGELOG.md.next
        mv CHANGELOG.md.next CHANGELOG.md
    fi
    if [[ -t 0 ]]; then
        "${VISUAL:-${EDITOR:-vi}}" CHANGELOG.md
    fi
    echo "CHANGELOG.md entry of $tag:"
    awk -v entry="$open_entry" '$0 == entry { inside = 1; next } inside && /^## \[/ { exit } inside' CHANGELOG.md
fi
read -r -p "Sign and push $tag on $(git rev-parse --short HEAD)? [y/N] " answer || answer=
if [[ $answer != [yY] ]]; then
    git checkout -- CHANGELOG.md
    die "Nothing tagged."
fi

start=$(git rev-parse HEAD)
step=
on_error() {
    {
        echo "Release $tag failed at step '$step'. To recover:"
        case $step in
        changelog | tag | push-develop)
            echo "  git tag -d $tag 2>/dev/null   # nothing was pushed for it"
            [[ $mode == pre ]] || echo "  git reset --hard $start   # drops the release commit only"
            ;;
        push-tag)
            echo "  git push origin $tag"
            [[ $mode == pre ]] ||
                echo "  then add the '$open_entry' entry above the first '## [' line of CHANGELOG.md," \
                    "commit it signed and git push origin develop"
            ;;
        open-entry)
            echo "  add the '$open_entry' entry above the first '## [' line of CHANGELOG.md if missing, commit it" \
                "signed, then git push origin develop"
            ;;
        esac
    } >&2
}
trap on_error ERR

if [[ $mode != pre ]]; then
    step=changelog
    sed -i "s/^## \[0\.0\.0\] - 202X-XX-XX\$/## [$version] - $(date +%Y-%m-%d)/" CHANGELOG.md
    git commit -q -S -m "chore(release): $tag" CHANGELOG.md
fi
step=tag
git tag -s "$tag" -m "Release $tag"
step=push-develop
git push origin develop
step=push-tag
git push origin "$tag"
if [[ $mode != pre ]]; then
    step=open-entry
    awk -v entry="$open_entry" '!done && /^## \[/ { print entry; print ""; done = 1 } { print }' CHANGELOG.md \
        >CHANGELOG.md.next
    mv CHANGELOG.md.next CHANGELOG.md
    git commit -q -S -m "chore(release): open the next changelog entry" CHANGELOG.md
    git push origin develop
fi
trap - ERR
[[ $mode == pre ]] && index=testpypi || index=pypi
echo "Approve the $index deployment: https://github.com/pprados/pysandboxes/actions/workflows/release.yml"
