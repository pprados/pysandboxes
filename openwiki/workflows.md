# Workflows in Py-Sandboxes

## Overview
This section presents the workflows associated with the application and configuration of Py-Sandboxes within various Python environments. The goal is to highlight integration steps, common usage scenarios, and best practices.

## Common Workflows

### Full Application Sandboxing
- **Objective**: Apply security measures across the entire Python application to restrict unauthorized access and operations.
- **Steps**:
  1. Install Py-Sandboxes.
  2. Configure the `pyproject.toml` to enforce full application sandboxing.
  3. Launch application ensuring the sandbox mechanisms are in place.
  4. Validate through testing to ensure all security filters are operational.

### Partial Application Sandboxing
- **Objective**: Target specific modules or functions for sandboxing without impacting global application performance.
- **Steps**:
  1. Identify high-risk modules requiring enhanced security.
  2. Use Py-Sandboxes to wrap these modules with necessary security filters.
  3. Test individual modules to ensure expected behavior while under sandbox restrictions.

### Sandbox Configuration
- **Scenario**: Customize sandbox settings to suit specific application needs, balancing between security and performance.
- **Example Configurations**:
  - Adjust API interceptions based on application requirements.
  - Create explicit whitelists for files and environments.
  - Set network access and subprocess execution restrictions.

For detailed instructions and examples, refer to the sample-specific guides linked in the documentation.
