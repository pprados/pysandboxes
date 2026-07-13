# Implementation

## Strategy
- All the py-sandbox are a dynamic patch of python API
- To avoid having to load all modules in order to patch them before launching the program, we use a clever strategy. A specific import implementation is added. It imports the modules in the usual way and, if necessary, adds the changes required to protect the code.
- This mechanism also allows authorized modules to be filtered.
- Standard functions are replaced by versions that will check the parameters and possibly transform them.
For file management, names will be checked against exclusion rules and modified if there is an expose parameter indicating a new name for the directories. If a file is not found in the expose rules, an exception is raised.
- For network connection processing, the procedure is similar. Connection settings are validated against various rules. DENY rules take priority so that a wide range of IP addresses can be ALLOWED, with certain addresses excluded. For example, accept all connections except localhost or intranet addresses.
- Import rights and call rights are two distinct notions. A module may legitimately be importable while some of its functions must stay out of reach. A registry of 103 sensitive functions (`os.system`, `subprocess.Popen`, `os.kill`, `ctypes.CDLL`, ...) is therefore denied by default, whatever `python-import=` allows, and a call right is never derived from a module being present in `python-import=`.
- For filtering environment variables, processing is performed before the sandbox is launched. This process is launched with only the variables that it has visibility of.


## Current implementation

### Complete mode
Here is a brief description of the implementation in **complete mode**. You will find more details by consulting the code.

- Command-line parameters are parsed and classified into two groups: python program parameters and py-sandboxes parameters.
- This process continues until the presence of the  `-c`, `-m`, or `<script.py>` parameters.
- The configuration files are consulted.
- The **os-sandbox** parameter is extracted.
- Environment variables are injected into the configuration files.
- The parameters are converted into specific parameters for **os-sandbox**.
- Parameters may be modified to account for the specificities of the **os-sandbox** implementation. For instance, applying a double expose mapping to directories is not relevant.
- A standard `python` program is launched within the *OS sandbox technology* using the extracted python parameters and `-m pysandboxes.remote.main_sandbox`.
- The sandbox\'s parameters, state, and log format are transmitted to the sandbox via a *named pipe*.
- The main function read the configuration and detects the use of `python-sb`.
- The sandbox is activated.
- The API guard is armed just before your program takes over, so the framework's own startup calls need no exemption.
- A simulation of a standard python startup (managing modules, scripts, commands, and interactive mode) is implemented to launch your program in the sandbox.
- If interactive mode is used, the code detects whether it's a standard interface or the IPython CLI. The code then adjusts its headers and parameters to indicate the presence of the sandbox.

### Selected mode
Here is a brief description of the implementation in **partial mode**. You will find more details by consulting the code.

- The parameter files are consulted.
- The `os-sandbox` parameter is extracted.
- The environment variables are injected in the config lines
- The parameters are converted into specific parameters for **os-sandbox**.
- The parameters may undergo modifications to take into account the specificities of the **os-sandbox** implementation. For example, applying a double `expose-ro` / `expose-rw` on directories is not relevant.
- A free TCP port is selected
- a classical `python` program is started in the sandbox technology, with the extracted classical python parameter and the module `-m pysandboxes.remote.main_sandbox\'
- The sandbox\'s parameters, port, state, and log format, as well as a random token, are transmitted to the sandbox via a *named pipe*.
- In the sandbox
  - An HTTP FastAPI server is launched with the selected port.
      - It implements the SSE protocol.
      - The sandbox is activated.
          - A Finder/Loader pair is added to `sys.meta_path`.
          - All modules (except some critical ones) are uninstalled or reloaded.
          - From now on, when a module is loaded, it undergoes *on-the-fly* modifications.
          - Critical functions and methods are re-implemented to follow the security rules.
      - Upon receiving an SSE request:
          - The token is verified.
          - The API guard is armed. The call is idempotent, so every entry point may make it.
          - A specific context is created to capture *stdout* and *stderr*.
          - The module corresponding to the function is imported.
          - The `@sandbox` function is invoked.
          - It detects that it is already running in a sandbox and then starts the normal execution.
          - A message stream goes up to the client with the uses of *stdout* and *stderr*.
          - The function\'s return or exception goes back to the caller.
          - If an exception is raised, the remote stack trace is injected, and the exception is propagated again.
          - The connection is terminated.
      - If an SSE request fails, it is retried after a delay.
      - If the sandbox falls (the process dies)
        - it is restarted.
        - The `init_fn` function is executed again, then communication resumes.
      - If a *shutdown* of the daemon is requested
        - All future incoming request are block
        - Waiting the end of all current request
        - Say it's done for the main process
        - Start to *shutdown* the daemon
  - If the daemon is stopped, a watchdog can detect this situation
    - The child process is restarted
    - The current requests are retry multiple times to be reconnected to the new child process.

### Sensitive API calls
The `python-api=` rules are enforced by `pysandboxes/guard_api.py`, on top of the same patching machinery as the other guards.

- The registry `SENSITIVE_API` is the single source of truth. It maps six categories (`process-exec`, `process-control`, `privileges`, `threads`, `native`, `introspection`) to their qualified function names, and it drives three things at once: the patch table, the validation of the profile targets, and the documentation.
- Low-level aliases are registered next to the name you write in your code, because `os` does `from posix import *`: `os.system` **is** `posix.system`. Whenever a function is registered, both spellings are, so the low-level one cannot be used to walk around the high-level one. A few sensitive functions stay out of this registry on purpose, because another guard covers them better: `os.chroot` and `posix.chroot` are patched by the file layer, with a path check rather than a binary allow or deny.
- Any target absent from the registry, unknown category or unknown function, is a configuration error raised at startup. A typo such as `python-api=ALLOW:os.systemm` fails immediately, instead of silently leaving a hole.
- The rules are flattened once into one decision per registered function. Resolution is by *specificity*, not by order: a rule on a function always beats a rule on its category, wherever the lines sit, which keeps `include` composition predictable. `DENY` wins at equal specificity, which is the fail-safe choice. The wrapper then performs a single dictionary lookup, whatever the number of rules.
- A single parameterised wrapper is installed on every entry, rather than one function per target.
- Enforcement is *armed* rather than exempted. The wrappers let everything through until `arm()` is called, and `arm()` is called immediately before user code takes over. Framework code therefore runs while the guard is disarmed and needs no exemption, no caller-frame check and no `original()` escape hatch, all of which would be forgeable from inside the sandbox.
- One call can cross several guarded doors in series, because some of these functions delegate to others in the registry (`subprocess.getoutput` reaches `os.posix_spawn`, `pty.spawn` reaches `os.fork`, `threading.Thread.start` reaches `threading._start_joinable_thread`, ...). Allowing the outer name alone is then refused on the inner one. Each refusal names the door it stopped at, so iterating converges.
- The thread launch primitive moved between the supported interpreters: 3.11 and 3.12 expose `threading._start_new_thread`, while 3.13 replaces it by `threading._start_joinable_thread`. Both spellings are registered so a profile stays portable, and only the applicable ones are patched.
- In learning mode the wrapper records the call and never fails, like the import guard. Only calls that are not already allowed are recorded, and the category is inferred at write time: if the functions already allowed by the profile plus the functions just learned cover a category completely, the single category line is emitted, otherwise one line per function. The two forms are exclusive, so least privilege is the default outcome rather than a convention.
- On the partial-mode path the daemon rebuilds the rule set field by field, and the API rules are propagated with it, so `@sandbox` and `sandboxes()` are subject to the same decisions as a full `python-sb` run.
- The `native` and `introspection` categories are detection and friction, not a barrier. Sandboxed code can undo Python-level patches, as the [weaknesses](weaknesses.md) page records. The **os-sandbox** remains the real barrier.

### Pin DNS
DNS is a significant difficulty when using **OS-Sandbox**. Indeed, if we want to add netfilter rules, it is the host that must resolve the domain names to obtain a list of IP addresses. Then, a netfilter file allows these addresses to be used to limit access. But, the sandbox will itself want to resolve the same domain names. It is possible that it will receive different IP addresses. The network rules are then no longer compatible. For example, google.com can be resolved to dozens of IP addresses. Netfilter is not compatible with DNS.

To work around this difficulty, before launching the sandbox, during the analysis of the rules, a pined-DNS is created, with the rules injected into netfilter. This DNS is then injected into the python APIs, so that the domain names return the same IP addresses and the netfilter rules work correctly.
