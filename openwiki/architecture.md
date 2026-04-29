# Architecture of Py-Sandboxes

## Overview
The architecture of Py-Sandboxes is designed to enhance the security of Python applications by enforcing sandboxing mechanisms that restrict unauthorized actions and control code execution environments.

## Sandbox Mechanisms

### Complete Mode
- **Purpose**: Applies the sandbox to the entire application. This mode is used when maximum security is desired, ensuring that all executed code passes through predefined security layers.
- **Implementation**: Utilizes Python API interception to monitor and restrict certain actions. Security filters are applied to prevent access to sensitive functions and modules unless explicitly allowed.

### Partial Mode
- **Purpose**: Allows specific sections of code to be sandboxed. This mode offers flexibility, balancing performance needs with enhanced security.
- **Implementation**: Similar to complete mode, but applied selectively to parts of the application. It ensures that only critical or risky components of the code are sand-boxed, thereby optimizing run-time efficiency.

## Technical Implementation
- **API Interception**: Python's dynamic nature allows for API call interception, which forms the basis of the sandbox functionality. Calls to sensitive operations are wrapped with security checks.
- **Security Filters**: Implement pre-emptive filtering to index and monitor file system access, network interactions, and execution of subprocesses.
- **Layered Security**: Incorporation of `os-sandbox` alongside `py-sandbox` for robust, multi-layered protection mimicking models like [AppArmor](https://apparmor.net/).

## Benefits
- **Security Enhancement**: Drastically reduces the attack surface by controlling executable paths and process privileges.
- **Flexibility**: Provides optional configurations and extensibility through multiple sandbox modes.
- **Integration Support**: Seamlessly integrates with popular frameworks and tools, facilitating broader adoption and security upgrading.

For detailed workflow examples and data model specifics, please refer to the respective sections in the documentation.
