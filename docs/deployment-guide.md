# Deployment Guide – pysandboxes

**Date:** 2026-03-12

## Container image (python-sb)

- **Dockerfile:** Builds from `python:${PYTHON_VERSION}-slim`; installs system deps (iptables, iproute2, slirp4netns for unshare), copies wheel from `dist/`, installs with pip. No ENTRYPOINT; default CMD is `python-sb`.
- **Build:** From project root, run `make dist` then `make build-image` (or use `build-image-docker` / podman). Image tag: `python-sb:latest` (and `python-sb:$(PYTHON_VERSION)`).
- **Run:** e.g. `docker run --rm python-sb:latest python-sb --help` or `OS_SANDBOX=unshare python-sb -m tests.integration_tests.tst_usage`.

## CI/CD

- GitHub Actions (or similar) can run `make validate` (format, lint, spell_check, all-tests). Container tests require Docker/Podman and optionally minikube (see Makefile `minikube-ready`, `container-tests`).
