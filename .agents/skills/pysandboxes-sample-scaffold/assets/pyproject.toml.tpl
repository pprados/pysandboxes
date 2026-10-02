[project]
name = "{{SAMPLE_NAME}}"
version = "0.1.0"
description = "{{DESCRIPTION}}"
readme = "README.md"
requires-python = ">=3.11"
authors = [{ name = "{{AUTHOR}}" }]
keywords = ["sandboxes", "{{KEYWORDS}}"]
license = { text = "MIT" }
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
]
dependencies = [
    "pysandboxes",
    # Add runtime dependencies here
]

[dependency-groups]
dev = [
    "ipython",
    "pyright>=1.1.379",
    "ruff>=0.6.9",
]
test = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-mock>=3.14.0",
]
codespell = [
    "codespell>=2.2.5",
]

[project.scripts]
{{SAMPLE_NAME}} = "{{PACKAGE_DIR}}.main:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["{{PACKAGE_DIR}}"]

[tool.pyright]
include = ["{{PACKAGE_DIR}}", "tests"]
venvPath = "."
venv = ".venv"

[tool.black]
line-length = 120
target-version = ["py310"]

[tool.ruff.lint]
select = ["E", "F", "I"]
ignore = []

[tool.ruff]
line-length = 120
target-version = "py310"

[tool.codespell]
skip = ".git,*.pdf,*.svg,*.yaml,*.ipynb,uv.lock,./.venv"

[tool.uv]

[tool.uv.sources]
# Use only inside the pysandboxes git repository
pysandboxes = { path = "../..", editable = true }

[tool.pytest.ini_options]
addopts = "--strict-markers --strict-config -vv"
