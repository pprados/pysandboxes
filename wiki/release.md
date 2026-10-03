# Releasing — how a pre-release reaches test.pypi.org and Docker Hub

This page is for maintainers. A signed tag pushed by the maintainer is the only way to publish: the wheel goes to
test.pypi.org, then five container images go to Docker Hub. Only pre-releases (`X.Y.Z` followed by `a`, `b` or `rc`
and a number) are enabled; a final tag such as `v0.1.0` is refused until final versions are opened to pypi.org.

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
integration, sample and container suites; a tag on the same commit reuses that run instead of repeating it. A tag on
any other commit runs the suites itself, without the `qemu-tcg` rows, which takes about twenty minutes more.

A published tag is never moved nor deleted. If a release fails after the upload, fix `develop` and publish the next
number.

## Final versions (not enabled yet)

`make publish-patch` and `make publish-minor` will publish final versions once `release.yml` accepts `vX.Y.Z` tags:
they run `make release` (`validate` and `all-tests`) first, take the last final tag (`v0.0.0` without one) bumped
by patch or minor, date the `[0.0.0]` entry of `CHANGELOG.md` in a signed commit, tag and push, then open a new
`[0.0.0]` entry. Until then they refuse at once, so a final tag can never be pushed by mistake and burn its number.

## What the pipeline does

| Job | What it checks or does |
|---|---|
| `verify` | The tag is a pre-release, annotated, signed by a key listed in `RELEASE_ALLOWED_SIGNERS`, on a commit of `develop` |
| `push-checks` | `lint.yml` and `test.yml` are green on the tagged commit (waits up to 30 min for them) |
| `validate` | `make validate` on Python 3.13, `pip-audit` included |
| `build` | `uv build`; the wheel version must equal the tag; `twine check` |
| `reuse-lookup` | Looks for a green `schedule` run of `full-gate.yml` on the same commit (a manual run never counts) |
| `full-gate` | The integration, sample and container suites, skipped when `reuse-lookup` found a nightly to reuse |
| `wheel-tests` | The unit tests against the built wheel, installed in a clean venv, on Python 3.11 to 3.14 |
| `publish-testpypi` | Waits for the approval, then uploads with Trusted Publishing and PEP 740 attestations |
| `verify-published` | Downloads the wheel back from test.pypi.org and compares its sha256 with the one built |
| `images` | Builds the five images from that wheel, smoke-tests them, pushes `docker.io/pprados/<image>:<version>` |

The images are `python-sb`, `python-sb-landlock`, `python-sb-unshare`, `python-sb-bwrap` and `python-sb-qemu`,
`linux/amd64`, Python 3.13. Only the version tag is pushed, never `latest`. Their digests are listed in the run
summary.

To publish the wheel alone, set the repository variable `RELEASE_IMAGES` to `false` before tagging
(`gh variable set RELEASE_IMAGES --body false`), and delete it afterwards (`gh variable delete RELEASE_IMAGES`).

## Who can publish

Anyone who can push to the repository can change `release.yml` and every file of a commit. What stops them from
publishing lives in GitHub settings, which write access cannot change:

- the tag ruleset `release-tags` lets only the maintainer create, move or delete a `v*` tag;
- the `testpypi` environment requires the maintainer's approval, and test.pypi.org accepts uploads only from that
  environment (Trusted Publishing, no stored token);
- the Docker Hub token lives in the `dockerhub` environment, which only `v*` tags can deploy to.

The images are pushed with that token rather than to ghcr.io with the workflow's own `GITHUB_TOKEN`: any workflow, on
any branch, can grant itself `packages: write`, so a non-maintainer could overwrite a published image.

## One-time settings

Already in place. Recreate them only if they are lost:

- repository variable `RELEASE_ALLOWED_SIGNERS`: one line, `<git user email> <public key>`, e.g.
  `gh variable set RELEASE_ALLOWED_SIGNERS --body "$(git config user.email) $(cat ~/.ssh/id_github.pub)"`;
- tag ruleset on `refs/tags/v*`: creation, update, deletion and non-fast-forward restricted, bypass: repository admin;
- environment `testpypi`: deployment tags `v*`, required reviewer the maintainer;
- on test.pypi.org, a trusted publisher: owner `pprados`, repository `pysandboxes`, workflow `release.yml`,
  environment `testpypi`;
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
| `verify` fails | Tag not signed, signed by an unlisted key, final version, or commit not on `develop`. Nothing published: fix, then tag the next number |
| `push-checks`: "push checks not finished" | `lint.yml` or `test.yml` did not finish within 30 min on the tagged commit. Re-run the failed jobs once they are green |
| `validate` fails on `pip-audit` | An advisory appeared since the last push. Relock the affected project (`uv lock --upgrade-package <pkg>`), or document an ignore in the `Makefile` when no fix exists; then tag the next number |
| `publish-testpypi` never starts | A gate failed, or `full-gate` was skipped by a failure rather than by a reuse. Nothing published |
| `verify-published`: "published but not visible yet" | test.pypi.org's CDN has not served the file within 10 min. Re-run the failed jobs |
| `verify-published`: the wheel "differs" | test.pypi.org holds another file for this version (a re-run rebuilt a different wheel; the upload is skipped when the version exists). Publish the next number |
| `images` fails at the smoke test | An image lacks the version or a provider binary. Nothing pushed |
| `images` fails while pushing | Part of the five images may be published. Re-run the failed jobs: the same tags are overwritten |
