# Ready image to run python-sb directly (no apt/pip at runtime).
# Python version comes from build-arg (make build-image uses uv's Python version).
# Build: (podman/docker) build --build-arg PYTHON_VERSION=3.13 -t python-sb:latest .
ARG PYTHON_VERSION=3.10
FROM python:${PYTHON_VERSION}-slim
LABEL org.opencontainers.image.version="${PYTHON_VERSION}"

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libvirt-dev \
    pkg-config && \
    pip install --upgrade pip && \
    pip install --no-cache-dir ipython && \
    pip cache purge && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# For unshare and bwrap sandboxes
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    bubblewrap \
    iptables \
    iproute2 \
    slirp4netns && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*


# Same working directory as the base python image
WORKDIR /app  # FIXME

## Copy wheel from dist/ (build with: make dist) and install the module
COPY dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl

# No ENTRYPOINT: you can run python-sb, bash, or a module.
# Example: python-sb --help  or  OS_SANDBOX=unshare python-sb -m tests.integration_tests.tst_usage
CMD ["python-sb"]
