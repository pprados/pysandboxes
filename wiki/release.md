# Releasing — how a tag reaches test.pypi.org or pypi.org, and Docker Hub

This page is for maintainers. A signed tag pushed by the maintainer is the only way to publish: the wheel goes to
test.pypi.org for a pre-release (`X.Y.Z` followed by `a`, `b` or `rc` and a number) or to pypi.org for a final version
(`vX.Y.Z`), then five container images go to Docker Hub.

## Publishing a pre-release

From an up-to-date `develop`, with a clean tree:

```bash
make publish-pre-release VERSION=0.1.0b5
```

The target refuses a malformed version, a dirty tree, another branch, a `develop` behind `origin/develop` and an
existing tag. It then shows what changed since the last tag in the pipeline and the wheel (`.github`, `Makefile`,
`pyproject.toml`, `uv.lock`, `pysandboxes`), asks for confirmation, signs the tag with your SSH key, and pushes
`develop` then the tag.

The tag starts `.github/workflows/release.yml`. When every check has passed, the run waits for **one approval**: the
`testpypi` deployment, in the run page or under Actions → Release. Approving publishes the wheel; the images follow
without a second click.

Tag a commit the nightly already proved, when you can. The nightly (`full-gate.yml`, 20:17 UTC on `develop`) runs the
integration, sample and container suites; a tag on the same code reuses that run instead of repeating it. The lookup
walks back over the release commit and over commits that touch only documentation, so a final version tagged right
after a green nightly reuses it. A tag on any other code runs the suites itself, without the `qemu-tcg` rows, which
takes about twenty minutes more.

A published tag is never moved nor deleted. If a release fails after the upload, fix `develop` and publish the next
number.

## Publishing a final version

`make publish-patch` and `make publish-minor` run `make release` (`validate` and `all-tests`) first, take the last
final tag (`v0.0.0` without one) bumped by patch or minor, date the `[0.0.0]` entry of `CHANGELOG.md` in a signed
commit, tag and push. `make publish-final VERSION=X.Y.Z` does the same with the version given, which must be greater
than the last final tag: it sets the first number of a series, such as `0.5.0`. Before tagging, `make publish-minor`
and `make publish-final` also run `make sample-tests-matrix`: every sample on every Python under `subprocess`,
`landlock`, `bwrap`, `firejail` and `unshare`, the grid `samples.yml` runs in CI. The tag holds no open entry; the
first merge into `develop` after the release opens a new `[0.0.0]` entry.

The first final version publishes the `[0.0.0]` entry as written. From the next one on, `scripts/changelog-draft.sh`
rewrites it before the tag: an LLM (`claude -p`, without tools, from the maintainer's logged-in shell) merges the
lines the entry holds with the `feat`, `fix`, `perf` and `security` commit subjects since the last final tag, into
`### Added`, `### Changed`, `### Fixed` and `### Security` bullets written for users. The entry then opens in
`$VISUAL`, `$EDITOR` or `vi`, and the confirmation question signs and tags what was saved; declining restores
`CHANGELOG.md`. An answer of the wrong shape, a failing or missing `claude` falls back to the entry followed by the raw
commit subjects: a release never depends on a model. `CHANGELOG_LLM` replaces the command. The tests that call a real
model are marked `llm` and run only with `RUN_LLM_TESTS=1`.

The tag starts `release.yml`, which waits for **one approval**, the `pypi` deployment. Approving publishes
`pysandboxes` and, when `python-sb/` changed since the last final tag, `python-sb` with a higher version. The run then
checks pypi.org, pushes the images with `3.X`, `3`, `latest` and `X.Y.Z` (plus `3.X-X.Y.Z`), and fast-forwards
`master` to the tagged commit. A version number uploaded to pypi.org can never be reused, even after deletion;
yanking only hides it.

## What the pipeline does

| Job | What it checks or does |
|---|---|
| `verify` | The tag is a pre-release or a final version, annotated, signed by a key listed in `RELEASE_ALLOWED_SIGNERS`, on a commit of `develop` |
| `push-checks` | `lint.yml` and `test.yml` are green on the tagged commit, or on the commit below a documentation-only release commit (waits up to 30 min for them) |
| `validate` | `make validate` on Python 3.13, `pip-audit` included |
| `build` | `uv build`; the wheel version must equal the tag; `twine check`. Also builds `python-sb` when it changed (below) |
| `reuse-lookup` | Looks for a green `schedule` run of `full-gate.yml` on the same code, walking back over release and documentation-only commits (a manual run never counts) |
| `full-gate` | The integration, sample and container suites, skipped when `reuse-lookup` found a nightly to reuse |
| `wheel-tests` | The unit tests against the built wheel, installed in a clean venv, on Python 3.11 to 3.14 |
| `publish-testpypi` | Waits for the approval, then uploads with Trusted Publishing and PEP 740 attestations |
| `publish-pypi` | Final tags only: waits for the `pypi` approval, then uploads `pysandboxes` and, when due, `python-sb` |
| `verify-published` | Downloads the wheel back from the index of the tag kind (pypi.org for a final tag, test.pypi.org otherwise) and compares its sha256 with the one built |
| `images` | One runner per Python 3.11 to 3.14: builds the five images from that wheel, smoke-tests them, pushes them to `docker.io/pprados/<image>` |
| `advance-master` | Final tags only: fast-forwards `master` to the tagged commit, never forced |

The images are `python-sb`, `python-sb-landlock`, `python-sb-unshare`, `python-sb-bwrap` and `python-sb-qemu`,
`linux/amd64`. The smoke test checks that each provider image runs every tool its provider invokes.
`.github/scripts/image-tags.sh` lists their tags, in the manner of the official `python` images: `<python>-<version>`
for every release, `<version>` for Python 3.14, plus `<python>` and, for Python 3.14, `3` and `latest` for a final
release only (see [Images on Docker Hub](docker-hub.md)).
Their digests are listed in the run summary.

`python-sb/` is a separate package, the one behind `uvx python-sb`, with its own version. A release publishes it
too when one of its files changed since the previous tag (the last final tag, for a final version); its version in
`python-sb/pyproject.toml` must then be higher than at that tag, or `build` fails and asks for the bump. Otherwise it
is left out. Its wheel is checked in `wheel-tests` and uploaded by `publish-testpypi` or `publish-pypi`, under the
same approval.
If that upload fails (no trusted publisher yet, rejected approval), re-run the failed jobs of the same run: a new tag
would compare `python-sb/` with the failed one, find no change, and never publish that version.

To publish the wheel alone, set the repository variable `RELEASE_IMAGES` to `false` before tagging
(`gh variable set RELEASE_IMAGES --body false`), and delete it afterwards (`gh variable delete RELEASE_IMAGES`).

## Who can publish

Anyone who can push to the repository can change `release.yml` and every file of a commit. What stops them from
publishing lives in GitHub settings, which write access cannot change:

- the tag ruleset `release-tags` lets only the maintainer create, move or delete a `v*` tag;
- the `testpypi` and `pypi` environments require the maintainer's approval, and test.pypi.org and pypi.org accept
  uploads only from them (Trusted Publishing, no stored token);
- the Docker Hub token lives in the `dockerhub` environment, which only `v*` tags can deploy to.

The images are pushed with that token rather than to ghcr.io with the workflow's own `GITHUB_TOKEN`: any workflow, on
any branch, can grant itself `packages: write`, so a non-maintainer could overwrite a published image.

## One-time settings

Already in place. Recreate them only if they are lost:

- repository variable `RELEASE_ALLOWED_SIGNERS`: one line, `<git user email> <public key>`, e.g.
  `gh variable set RELEASE_ALLOWED_SIGNERS --body "$(git config user.email) $(cat ~/.ssh/id_github.pub)"`;
- repository variable `RELEASE_SKIP_FULL_GATE` (temporary): `true` skips the integration, sample and container
  suites, as a reused nightly would; the light gate, `wheel-tests` and the approval still apply. Delete it after use;
- tag ruleset on `refs/tags/v*`: creation, update, deletion and non-fast-forward restricted, bypass: repository admin;
- environment `testpypi`: deployment tags `v*`, required reviewer the maintainer;
- on test.pypi.org, a trusted publisher: owner `pprados`, repository `pysandboxes`, workflow `release.yml`,
  environment `testpypi`; and the same for the project `python-sb` (a pending publisher, until its first upload);
- environment `pypi`: deployment tags `v*`, required reviewer the maintainer;
- on pypi.org, a trusted publisher in the `pysandboxes` and `python-sb` projects: owner `pprados`, repository
  `pysandboxes`, workflow `release.yml`, environment `pypi`;
- environment `master`: deployment tags `v*`, no reviewer, secret `MASTER_DEPLOY_KEY`: the private half of a deploy
  key with write access, which `advance-master` uses to fast-forward `master` (`GITHUB_TOKEN` cannot push workflow
  files): `ssh-keygen -t ed25519 -N '' -C release-master -f /tmp/master-key`,
  `gh repo deploy-key add /tmp/master-key.pub --allow-write --title release-master`,
  `gh secret set MASTER_DEPLOY_KEY --env master < /tmp/master-key`, then `rm /tmp/master-key*`;
- environment `dockerhub`: deployment tags `v*`, no reviewer, secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` (a
  Docker Hub personal access token, Read & Write). No `DOCKERHUB_*` secret may exist at repository level, where every
  branch could read it:

  ```bash
  gh api -X PUT repos/pprados/pysandboxes/environments/dockerhub \
    --input - <<<'{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}'
  gh api -X POST repos/pprados/pysandboxes/environments/dockerhub/deployment-branch-policies \
    -f name='v*' -f type=tag
  gh secret set DOCKERHUB_USERNAME --env dockerhub --body pprados
  gh secret set DOCKERHUB_TOKEN --env dockerhub
  ```

## When a release fails

| Symptom | Cause and way out |
|---|---|
| `verify` fails | Tag not signed, signed by an unlisted key, or commit not on `develop`. Nothing published: fix, then tag the next number |
| `push-checks`: "push checks not finished" | `lint.yml` or `test.yml` did not finish within 30 min on the tagged commit. Re-run the failed jobs once they are green |
| `validate` fails on `pip-audit` | An advisory appeared between the audit `tag-release.sh` runs before tagging and the run. Relock the affected project (`uv lock --upgrade-package <pkg>`), or document an ignore in the `Makefile` when no fix exists; then tag the next number |
| `publish-testpypi` or `publish-pypi` never starts | A gate failed, or `full-gate` was skipped by a failure rather than by a reuse. Nothing published |
| `verify-published`: "published but not visible yet" | The index's CDN (test.pypi.org or pypi.org) has not served the file within 10 min. Re-run the failed jobs |
| `verify-published`: the wheel "differs" | The index (test.pypi.org or pypi.org) holds another file for this version (a re-run rebuilt a different wheel; the upload is skipped when the version exists). Publish the next number |
| `images` fails at the smoke test | An image lacks the version or a provider binary. Nothing pushed |
| `images` fails while pushing | Part of the five images may be published. Re-run the failed jobs: the same tags are overwritten |
| `advance-master` fails | The `master` environment lacks `MASTER_DEPLOY_KEY`, or the key is wrong or read-only, or `master` is not an ancestor of the tag. Merge nothing, investigate, then push the tagged commit to `master` by hand |
