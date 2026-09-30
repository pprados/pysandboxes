# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
#
# Prepare a shell for the quick demo: `source init.sh`, from bash or zsh.
# The alias runs the `python-sb` of this repository, until the release that `uvx python-sb` needs is on PyPI.
# It names the venv's script directly: `uv run` may pick an active conda or virtual environment instead.
_demo_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
_repo_dir="$(cd "${_demo_dir}/../.." && pwd)"
uv sync --quiet --inexact --project "${_repo_dir}"
alias python-sb="'${_repo_dir}/.venv/bin/python-sb'"
export DEMO_API_KEY=sk-demo-123
export AWS_SECRET_ACCESS_KEY=do-not-leak  # a secret the application never needs
cd "${_demo_dir}" && find . -maxdepth 1 -name '.py-sandboxes*' -delete  # no policy yet: the audience must see it being born
unset _demo_dir _repo_dir
