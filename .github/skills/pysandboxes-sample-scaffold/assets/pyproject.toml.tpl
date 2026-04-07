[project]
name = "{{PROJECT_NAME}}"
version = "0.1.0"
description = "{{DESCRIPTION}}"
readme = "README.md"
requires-python = ">=3.10"
authors = [{ name = "{{AUTHOR}}" }]
keywords = ["sandboxes", "{{KEYWORDS}}"]
license = { text = "MIT" }
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
]
dependencies = [
    "pysandboxes",
    # Add runtime dependencies here
]

[dependency-groups]
dev = [
    "mypy",
    "black",
    "ruff>=0.6.9",
    "pyright>=1.1",
]
test = [
    "pytest>=8.3.3",
    "pytest-asyncio>=0.20.3",
    "pytest-dotenv>=0.5.2",
    "pytest-mock>=3.10.0",
]
codespell = [
    "codespell>=2.2.5",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["{{PACKAGE_DIR}}"]

[tool.pyright]
include = ["{{PACKAGE_DIR}}"]
venvPath = "."
venv = ".venv"

[tool.ruff.lint]
select = ["E", "F", "I"]
ignore = []

[tool.ruff]
line-length = 120
target-version = "py310"

[tool.uv]

[tool.uv.sources]
pysandboxes = { path = "../..", editable = true }

[tool.pytest.ini_options]
addopts = "--strict-markers --strict-config -vv"
testpaths = ["tests"]
