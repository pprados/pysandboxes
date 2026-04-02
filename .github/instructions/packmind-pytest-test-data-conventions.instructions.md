---
applyTo: 'All Python test files in tests/ and samples/*/tests/.'
---
## Standard: Pytest Test Data Conventions

Standardize pytest test data construction using conftest.py autouse and module-scoped fixtures, pytest.mark.parametrize, and MagicMock/AsyncMock to ensure consistent, isolated, and efficient test coverage. :
* Use autouse fixtures in conftest.py for shared environment setup instead of repeating setup code in each test
* Use MagicMock/AsyncMock for dependency isolation instead of custom stub classes
* Use module-scoped fixtures for expensive resources like daemon startup and event loop creation
* Use pytest.mark.parametrize for multi-case testing instead of manual loops or duplicated test functions

Full standard is available here for further request: [Pytest Test Data Conventions](../../.packmind/standards/pytest-test-data-conventions.md)