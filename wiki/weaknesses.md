# What are the weaknesses of py-sandbox?
There are several vulnerabilities in the proposed implementation. We are perfectly aware of them. The goal is not to execute unhealthy code, but to limit the malicious uses of our application.

Here are some vulnerabilities:

  - Each function or method patch must keep a link to the original method. An advanced introspection analysis can find it and invoke it outside of the security rules.
  - All classes are available via `object().__subclasses__()` and therefore also all modules. By analyzing this, it is possible to find the rules and modify them.
  - The variable `sys.meta_path` may be updated to remove the sandbox loader.
  - Any compiled code can have access to the entire Python memory and therefore find all secrets. A vulnerability in a Python library using compiled code can be exploited.
  - A child process, if it has the rights to read `/proc/${PPID}/environ`, can search for tokens there. **OS-sandboxes** generally prohibit this.
  - A direct network connection to the sandbox it's possible. A secret token, a random port and a limitation of localhost network are used.

We invite you to try out these approaches, without looking at the sources if you are gamers. This will teach you the ins and outs of Python. If you find any new vulnerabilities, we would be happy to hear about them. Note that the code is still hardened.
