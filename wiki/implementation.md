## Implementation
Here is a brief description of the implementation. You will find more details by consulting the code.

  - The parameter files are consulted.
  - The `os-sandbox` parameter is extracted.
  - The parameters are converted into specific parameters for **os-sandbox**.
  - The parameters may undergo modifications to take into account the specificities of the **os-sandbox** implementation. For example, applying a double `bind` on directories is not relevant.
  - A free TCP port is selected
  - A subprocess is launched with the selected **os-sandbox**.
  - The sandbox's parameters, port, state, and log format, as well as a random token, are transmitted to the sandbox via a *named pipe*.
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
      - If the sandbox falls (the process dies), it is restarted. The `init_fn` function is executed again, then communication resumes.
      - If an SSE request fails, it is retried after a delay.

