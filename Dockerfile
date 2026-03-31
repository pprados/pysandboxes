# Ready image to run python-sb directly (no apt/pip at runtime).
# Build: podman build -t pysandboxes:ready .   (or docker build)
# Run:  podman run -it --rm --privileged -v $(pwd):/app -w /app pysandboxes:ready \
#         OS_SANDBOX=unshare python-sb -m tests.integration_tests.tst_usage
FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libvirt-dev \
    pkg-config \
    iptables \
    iproute2 \
    slirp4netns \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Minimal copy for pip install (pyproject + readme required by hatch + package + tests)
# FIXME: final Dockerfile should use the published project version.
COPY pyproject.toml README.md ./
COPY pysandboxes/ pysandboxes/
COPY tests/ tests/

RUN pip install --no-cache-dir -e .

# No ENTRYPOINT: you can run python-sb, bash, or a module.
# Example: python-sb --help  or  OS_SANDBOX=unshare python-sb -m tests.integration_tests.tst_usage
CMD ["python-sb", "--help"]
