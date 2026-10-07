# FAQ

## How to display **py-sandbox** logs?
Set the level like this:
```python
logging.getLogger("Pysandboxes").setLevel(logging.INFO)
```
This specific logger carries the main information of the component.

If you want more intimate details, use:
```python
logging.getLogger("pysandboxes").setLevel(logging.DEBUG)
logging.getLogger("Pysandboxes").setLevel(logging.INFO)
```

## How to catch rule violation exceptions?
All rule violation exceptions are subclasses of the classic exceptions. They use multiple inheritance to be able to catch them all, regardless of their nature.

```python
from pysandboxes import SandBoxError

try:
  ...
except SandBoxError:
  ...  # Rule violated
```

> Exceptions are thrown if violations are detected by *py-sandbox* and not by *os-sandbox*.

## How to activate the sandbox in a notebook?
In on cell, you can use `with sandboxes()` or `run()`.
```python
# single cell
with sandboxes():
  ...
```

Between cells use:
```python
sb = sandboxes().__enter__()
```

## Why the current directory is used?
Sometime, with the learn process, the rule `expose-ro=.` is added. This is usually due to the presence of an `.env` file that is found by a library. This causes this directory to be added to the rules. You can set the variables manually and temporarily rename this file while the learning process is underway.

```bash
set -o allexport
source .env
set +o allexport
mv .env .env.bak
```
or
```bash
export $(grep -v '^#' .env | xargs)
```

## How to propagate a token to an API in the sandbox?
Replace:

```python
@sandbox
def call_llm():
  ...
```
with
```python
import os
from pysandboxes import sandbox


@sandbox
def _call_llm(token: str) -> None:
    print(f"{token=}")
    ...


def call_llm() -> None:
    return _call_llm(token=os.environ["LLM_TOKEN"])
```

## How to ensure a new version of a module doesn't hide new network accesses?
Using **Py-sandboxes** also makes you aware that a module update can also call the security rules into question.
We invite you, after each update, to test your application without learning. This way, if a rule is violated, you will know its origin.
See [use cases](use-cases.md) for this scenario and the others.

##  Do I have any new rule violations since the update?
Indeed, new ones can be proposed. As the approach is based on *denial by default*, these rules are rejected. Restart a learning session to add what is necessary.
Use the minor version to fix the version to used (`n.m.*`). The minor version is incremented for each new rules.

## Debugging
When using an external sandbox, two processes are launched. Your development environment is normally capable of handling this, if you use `os-sandbox=subprocess`. A breakpoint in a `@sandbox` function will interrupt the program in the sandbox process. Stack trace analysis will not be easy, as there is no complete trace of the call.

If an exception is generated at this level, the stack trace will be adjusted to show the direct path, abstracting the communication layer.

### OS-sandbox debugging
To know precisely the parameters used to launch an **OS-sandbox**, and to test the behavior,
use `python-sb`.

Depending on the technologies, it may be possible to connect directly to the **os-sandbox**. For example, for firejail, use `firejail --join=firejail-sandbox`.

Consult the corresponding documentation.

### How to disable py-sandbox?
Sometimes the sandbox disrupts development. There are several approaches to disabling the sandbox while adjusting the code.

To disable only one rule family, use the generic acceptance settings.
- `env=*=${*}`
- `expose-rw=/,/`
- `net=ALLOW|*|*|*|*`
- `python-import=*`
- `python-api=ALLOW:*`
- `eval-namespace=caller`: `eval()`, `exec()` and `compile()` run the source as is, with no validation, rewrite,
  budget or timeout. `python-api=ALLOW:dynamic-code` does the same before any `eval-*` rule is read, so
  `python-api=ALLOW:*` above also lifts the `eval-*` rules
- `remote-result-mode=objects`, then `remote-result-guard=false`: the value a `@sandbox` function returns is rebuilt in
  the caller as any object, then without the denylist of dangerous classes

Or
- Use the `py-sandbox=False` parameter. This keeps the **OS-sandbox** execution with the two-process architecture, but the security rules are not activated. The Python code is not patched. Combined with `os-sandbox=subprocess`, the OS-level sandbox is not used.
- Use the `learn=.py-sandboxes` parameter. This activates learning for all launches. As soon as an alert should be triggered, it is replaced by the addition of a new rule at the end of the execution.
- Use the special `os-sandbox=none` to deactivate all the `@sandbox` annotations. The stack trace show the direct call of the functions.

## How to package the project
The `.py-sandboxes` file must be adjusted for the execution environment. Use environment variables to be able to reuse it in different contexts.
The file must also be published in the project's module directory.

The best practice it to build a wheel, with your rules.
```toml
include = [
    { include = "my-package/.py-sanboxes" }
]
```
If you want to allow rules from the working directory to be added when using your module, add the following instructions to your `my_module/.py-sandboxes` file. Then the user can change some rules.
```ini
# File my_module/.py-sandboxes
include "./.py-sandboxes"
# ... specific rules
```

## What does the sandbox cost, and what does it break?

The performance impact is negligible, and nothing breaks as long as the privilege is granted. Once an access is authorized in `.py-sandboxes`, the call behaves exactly as it would outside the sandbox: the interception adds a whitelist check, not a re-implementation. What is *not* authorized raises an explicit error, which is the whole point.

Compiled extensions are a special case: since the Python layer cannot intercept them, they are neither slowed down nor restricted by it. A database driver written in C keeps working as before, and that is exactly the gap the OS layer is there to close.
