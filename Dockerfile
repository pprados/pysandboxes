# Base image: Python + wheel only. No OS provider (no unshare, bwrap, firejail, qemu).
# Build: make build-image-base  =>  python-sb:$(PYTHON_VERSION), python-sb:latest
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim
LABEL org.opencontainers.image.version="${PYTHON_VERSION}"

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config && \
    pip install --upgrade pip && \
    pip install --no-cache-dir ipython && \
    pip cache purge && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The caller names the wheel (make build-image-base passes it): dist/ may hold the
# builds of several commits, and installing them all makes pip refuse two versions
# of the same package.
ARG WHEEL
COPY dist/${WHEEL} /tmp/
RUN pip install --no-cache-dir /tmp/${WHEEL}

CMD ["python-sb"]
