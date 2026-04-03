# Ready image to run python-sb directly (no apt/pip at runtime).
# Python version comes from build-arg (make build-image uses uv's Python version).
# Build: (podman/docker) build --build-arg PYTHON_VERSION=3.13 -t python-sb:latest .
ARG PYTHON_VERSION=3.10
FROM python:${PYTHON_VERSION}-slim
ARG PYTHON_VERSION=3.10
LABEL org.opencontainers.image.version="${PYTHON_VERSION}"

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libvirt-dev \
    pkg-config \
    && pip install --upgrade pip && \
    pip install --no-cache-dir ipython \
    && apt-get remove -y --purge build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# For unshare sandbox
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    iptables \
    iproute2 \
    slirp4netns


# Same working directory as the base python image
WORKDIR /app  # FIXME

## Copy wheel from dist/ (build with: make dist) and install the module
COPY dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl

# No ENTRYPOINT: you can run python-sb, bash, or a module.
# Example: python-sb --help  or  OS_SANDBOX=unshare python-sb -m tests.integration_tests.tst_usage
CMD ["python-sb"]
