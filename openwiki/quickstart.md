# Quickstart Guide for Py-Sandboxes

## Overview

Py-Sandboxes aims to secure Python applications by restricting unauthorized execution of potentially harmful or malicious code, especially that which might be generated or manipulated by Language Models (LLMs). This project introduces a defense-in-depth approach to application security through Python-specific sandboxes.

## Key Features

- **Complete and Partial Sandboxing**: Ability to apply sandboxing techniques to entire applications or specific parts, enhancing security for Python code execution.
- **Security Filters**: Intercept and strengthen standard Python APIs to limit action capabilities.
- **Integration Support**: Designed to work with popular agent frameworks and LLMs to bolster security without compromising functionality.

## Installation

To get started with Py-Sandboxes, install the package from the GitHub repository:

```bash
pip install pysandboxes
```

Alternatively, for a direct GitHub install:

```bash
pip install git+https://github.com/pprados/pysandboxes.git
```

## Usage

- **Complete Mode**: Apply the sandbox to the entire application ensuring all code execution passes through security layers.
- **Partial Mode**: Allows specific application parts to be sandboxed, minimizing the performance overhead while still enhancing security.

For detailed usage scenarios and examples, refer to the [usage section](#) in the documentation.

## Security Goals

- **Path Traversal Reduction**: Restrict directory access to whitelisted paths.
- **Remote Code Execution Protection**: Remove sensitive APIs from code execution paths.
- **Excessive Permissions Control**: Enforce controlled access to files and environment variables.
- **Denial of Service Mitigation**: Implement timeouts and action restrictions to prevent misuse or performance degradation.

## Next Steps

- [Understand the Architecture](architecture.md)
- [Explore Workflows](workflows.md)
- [Review Data Models](data-models.md)
- [Testing Guidelines](testing.md)
- [Integrations Overview](integrations.md)

Join our community and contribute on [GitHub](https://www.github.com/pprados/pysandboxes)! For more detailed information, view our complete documentation in the sections provided above.
