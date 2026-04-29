# Data Models and Configuration in Py-Sandboxes

## Overview
This section describes the configuration and data models used in the Py-Sandboxes project. It includes insights into project dependencies, configurations, and environmental setups necessary for effective sandbox controls.

## Core Configuration Files

### `pyproject.toml`
- **Purpose**: Central configuration file for the project that defines dependencies, build instructions, and optional features for different sandbox providers.
- **Key Sections**:
  - **Dependencies**: Lists packages required for basic and full functionality, including `anthropic`, `fastapi`, `aiohttp`, and others for specific features.
  - **Optional Dependencies**: Configuration for OS-specific sandbox enhancements via providers like `bwrap`, `firejail`, and `landlock`.

### Environment Configurations
- **`.env` Files**: Used for setting environment-specific variables and secrets without exposing them in code or version control (ensure `.env` only contains non-sensitive info or exemplars).

## Dependency Management
- **Development**: Dependencies outlined for development include utilities such as `pre-commit`, `ipython`, and `pytest` variants for testing.
- **Testing**: Essential libraries for running comprehensive test suites like `pytest`, `pytest-asyncio`, and `pytest-dotenv`.

## Optional and Additional Add-ons
- Support for provider-specific extras, facilitating security extensions tailored to diverse operating systems.

Consult the [architecture](architecture.md) and [workflows](workflows.md) documents for more details on how these configurations influence sandbox behavior and application integration.
