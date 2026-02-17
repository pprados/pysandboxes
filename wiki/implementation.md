# Implementation

## Stategy
- All the py-sandbox are a dynamic patch of python API
- To avoid having to load all modules in order to patch them before launching the program, we use a clever strategy. A specific import implementation is added. It imports the modules in the usual way and, if necessary, adds the changes required to protect the code.
- This mechanism also allows authorized modules to be filtered.
- Standard functions are replaced by versions that will check the parameters and possibly transform them.
For file management, names will be checked against exclusion rules and modified if there is a bind parameter indicating a new name for the directories. If a file is not found in the bind rules, an exception is raised.
- For network connection processing, the procedure is similar. Connection settings are validated against various rules. DENY rules take priority so that a wide range of IP addresses can be ALLOWED, with certain addresses excluded. For example, accept all connections except localhost or intranet addresses.
- For filtering environment variables, processing is performed before the sandbox is launched. This process is launched with only the variables that it has visibility of.


## Current implementation
Here is a brief description of the implementation. You will find more details by consulting the code.

  - The parameter files are consulted.
  - The `os-sandbox` parameter is extracted.
  - The environement variables are injected in the config lines
  - The parameters are converted into specific parameters for **os-sandbox**.
  - The parameters may undergo modifications to take into account the specificities of the **os-sandbox** implementation. For example, applying a double `bind` on directories is not relevant.
  - A free TCP port is selected
  - A subprocess is launched with the selected **os-sandbox**.
  - The sandbox's parameters, port, state, and log format, as well as a random token, are transmitted to the sandbox via a *named pipe*.
  - In the sandbox
    - An HTTP FastAPI server is launched with the selected port.
        - It implements the SSE protocol.
        - The sandbox is activated.
            - A Finder/Loader pair is added to `sys.meta_path`.
            - All modules (except some critical ones) are uninstalled.
            - From now on, when a module is loaded, it undergoes *on-the-fly* modifications.
            - Critical functions and methods are re-implemented to follow the security rules.
        - Upon receiving an SSE request:
            - The token is verified.
            - A specific context is created to capture *stdout* and *stderr*.
            - The module corresponding to the function is imported.
            - The `@sandbox` function is invoked.
            - It detects that it is already running in a sandbox and then starts the normal execution.
            - A message stream goes up to the client with the uses of *stdout* and *stderr*.
            - The function's return or exception goes back to the caller.
            - If an exception is raised, the remote stack trace is injected, and the exception is propagated again.
            - The connection is terminated.
        - If an SSE request fails, it is retried after a delay.
        - If the sandbox falls (the process dies)
          - it is restarted.
          - The `init_fn` function is executed again, then communication resumes.
        - If a shutdown of the daemon is requested
          - All future incomming request are block
          - Waiting the end of all current request
          - Say it's done for the main process
          - Start to shutdown the daemon
    - If the daemon is stopped, a watchdog can detect this situation
      - The child process is restarted
      - The current requests are retry multiple times to be reconected to the new child process.

