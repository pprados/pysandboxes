FROM debian:bookworm
ENV DEBIAN_FRONTEND=noninteractive \
    UV_LINK_MODE=copy \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git build-essential bubblewrap firejail \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# scanner contract: the checkout lives inside the image, at /src
COPY . /src
WORKDIR /src

# Python, runtime and test dependencies are fetched here: the audit that follows has no network.
RUN uv python install 3.13 && uv sync --python 3.13 --frozen

# Cheap check that the image works; a failing test must not abort the build.
RUN (uv run --frozen pytest -q -x tests/unit_tests/guard || echo "WARNING: unit tests reported failures")
