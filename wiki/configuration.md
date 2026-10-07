# Configuration files

## Manage config file locations

By default, the program looks for the file in the root directory of the **module** that launches the sandbox, or, for `python-sb script.py`, in the directory of the script. Otherwise, the `./.py-sandboxes` file is used. This can be modified before the program is launched. If you package your application in a Wheel, place your parameters within your module.

To address different scenarios, parameter files can have `include` instructions. This allows you to distribute parameters across different files and locations.

By default, you'll find this:

```text
#include "./.local.py-sandboxes"  # May be added to .gitignore
include "~/.config/py-sandboxes/user-py-sandboxes.profile"  # For user
include "/etc/py-sandboxes/global-py-sandboxes.profile"  # For node
```

Uncomment the first line to save the `./.py-sandboxes` file in the Git repository while allowing the developer to make local modifications in the `./.local.py-sandboxes` file (which should be added to `.gitignore`). It is not active by default: its path is resolved from the current directory, so whatever directory the program is launched from could add rules of its own. Accepting it is the user's decision.

Parameters for all of the user's projects can be present in `~/.config/py-sandboxes/user-py-sandboxes.profile`, and for the entire machine in `/etc/py-sandboxes/global-py-sandboxes.profile`.

By adding or removing `include` statements, you can select the different personalization scenarios you want. Note: if it does not exist, it is simply ignored.

With **python-sb**, a special parameter can be used to select the configuration.
Without it, `python-sb` reads the `.py-sandboxes` next to the script or in the directory of the `-m` module, and
`./.py-sandboxes` when there is none. Both `--pysandboxes-config=FILE` and `--pysandboxes-config FILE`
are accepted.

```bash
python-sb --pysandboxes-config=./.py-sandboxes -m ...
```

If the file does not exist, the first run learns the rules and writes them into it. To add rules to an existing
file, add `--learn`: without a value, it writes into the file of `--pysandboxes-config`, as written on the command
line (never into the resource of a module found by `-m`):

```bash
python-sb --pysandboxes-config=cfg/my-app.py-sandboxes --learn -m ...
```

`--learn=<file>` writes into another file.

### Lock the rules

Every `--key=value` given to `python-sb` is a rule, and it takes precedence over the file: `--expose-ro=/etc`,
`--os-sandbox=none` or `--py-sandbox=false` widen what the program may do, and `--learn` makes it allowed to do
anything. Once a rule file is reviewed, write in it, or in a file it includes:

```ini
learn=false
```

From then on, the configuration is refused at startup when:

- the learning mode is requested, by `--learn`, by a `learn=<file>` in another file, or because the rule file does
  not exist;
- `python-sb` receives a rule on its command line, or the code passes one to `sandboxes()` or `run()`.

The lock only holds while the file holding it is loaded: `--pysandboxes-config=` can name another file, so pin the
full command line where the program is launched.

---

## Integration in a module

It is possible to use the solution to integrate it into a module, when you install your *wheel*. To do this, the `.py-sandboxes` file must be placed at the root of your module, as a resource.

When the sandbox is activated, the code searches for the caller's module and checks whether the resource exists. If so, it is used to apply the security rules. Otherwise, the same file is searched for in the working directory.

If you want to allow rules from the working directory to be added when using your module, add the following instructions to your `my_module/.py-sandboxes` file

```ini
# File my_module/.py-sandboxes
include "./.py-sandboxes"
# ... specific rules
```

To create a CLI that uses **py-sandboxes**, use the following pattern:

```python
def main() -> int:
    # ...
    print("hello")
    return 99

def main_sb() -> int:
    import sys
    import os

    sys.argv = (
            [
                __file__,
                "-m", globals()['__spec__'].name
            ] +
            sys.argv[1:])
    from pysandboxes.python_sb import main
    return(main())  # Launch 'python-sb'
```

And declare it in your TOML file.

```TOML
[project.scripts]
my-script = "my_module:main_sb"
# my-script = "my_module:main"  # Without sandboxes
```
