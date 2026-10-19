# Configuration files

## Manage config file locations

The program first checks the directory of the module that launches the sandbox. For `python-sb script.py`, it checks the script's directory. Otherwise, it uses `./.py-sandboxes`. Set another path before launch. For a packaged application, include the rules in the module.

Use `include` to split rules across files and locations.

By default, you'll find this:

```text
#include "./.local.py-sandboxes"  # May be added to .gitignore
include "~/.config/py-sandboxes/user-py-sandboxes.profile"  # For user
include "/etc/py-sandboxes/global-py-sandboxes.profile"  # For node
```

Uncomment the first line to keep `.py-sandboxes` in Git and allow local overrides in `.local.py-sandboxes`. Add the local file to `.gitignore`. The include is disabled by default because its path resolves from the current directory. Enabling it lets the launch directory add rules.

Parameters for all of the user's projects can be present in `~/.config/py-sandboxes/user-py-sandboxes.profile`, and for the entire machine in `/etc/py-sandboxes/global-py-sandboxes.profile`.

Add or remove `include` lines to select profiles. A missing included file is ignored; an unreadable file rejects the configuration. Bare names such as `include "common"` resolve beside the including file. Relative paths containing `/` resolve from the current working directory. Use an absolute path or `~/` path when the location must not depend on the launch directory.

Use `include-platform=<sys.platform> "profile"` to load platform-specific rules, for example `include-platform=linux "linux.profile"`. The value must match `sys.platform`. Other platform profiles are ignored. Use this for OS-specific imports and API permissions.

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

### Review the learned rules before trusting them

Learning mode groups file accesses by directory rather than by file: reading one file directly under a
directory grants `expose-ro=` (or `expose-rw=`) on that whole directory, not only on the file that was read.
For a script launched from a project's root directory, a single relative `open("config.json")` can expose
the entire project tree, including files the program never touched. This is not narrowed to the individual
file (the rule syntax accepts a file path as well as a directory): the harness itself has to read the script
file to run it, so the script's own directory is already learned even when the application opens nothing
else there, and narrowing other reads in that same directory would not shrink the profile. A kernel-backed
OS provider (`landlock`, `bwrap`, `firejail`, `unshare`, `qemu`) also needs every `sys.path` entry, which
includes that directory, mounted for `os.listdir`/`os.scandir` to work at replay; this part is reasoned from
the provider code, not separately verified by replaying under one of them. When the working directory
differs from the script's own directory, there is no such floor: a relative-path read against an unrelated
current directory (for example the directory `python-sb` was launched from) grants that whole directory,
which can be far broader than anything replay requires. Always review and narrow the
`expose-ro=`/`expose-rw=` entries a learning run produced before using the generated profile.

### Lock the rules

Every `--key=value` given to `python-sb` is a rule, and it takes precedence over the file: `--expose-ro=/etc`,
`--os-sandbox=none` or `--py-sandbox=false` widen what the program may do, and `--learn` makes it allowed to do
anything. Once a rule file is reviewed, write in it, or in a file it includes:

```ini
learn=false
```
or in command line:
```bash
python-sb --learn=false ...
```


From then on, the configuration is refused at startup when:

- the learning mode is requested, by `--learn`, by a `learn=<file>` in another file, or because the rule file does
  not exist;
- `python-sb` receives a rule on its command line, or the code passes one to `sandboxes()` or `run()`.

The lock only holds while the file holding it is loaded: `--pysandboxes-config=` can name another file, so pin the
full command line where the program is launched.

---

### Interactive sessions and IPython

When `python-sb` (or `ipython-sb`) opens an interactive session and IPython is installed, it gives the session a
private, temporary `IPYTHONDIR`, removed at exit. IPython runs every file of
`<IPYTHONDIR>/profile_default/startup/` when it starts: a session allowed to write into the user's own
`~/.ipython` could drop a file there, and that file would run later, outside the sandbox, in the next plain
`ipython`. The private directory keeps that persistence out of reach.

A profile may still set its own `env=IPYTHONDIR=...`: that line wins over the private directory, which is how a
locked profile (`learn=false`) declares one, since `python-sb` then adds no rule of its own. Do not point it at
`~/.ipython` while also exposing that directory read-write: the session could then plant a startup file that the
next unsandboxed IPython runs.

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
