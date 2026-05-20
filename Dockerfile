# Base image: Python + wheel only. No OS provider (no unshare, bwrap, firejail, qemu).
# Build: make build-image-base  =>  python-sb-base:$(PYTHON_VERSION), python-sb-base:latest
ARG PYTHON_VERSION=3.11
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

WORKDIR /app

COPY dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl

CMD ["python-sb"]
