# Roadmap
This version is a first implementation offered to the community. It allows for testing and demonstrating the validity of the approach.

It ensures that the patches for Python functions are correct and do not cause bugs in applications. If you find a case that presents a problem, open a ticket with a scenario to reproduce it. We will provide a fix as soon as possible.

It also verifies the relevance of the multiple sandbox encapsulation strategy. The latter was selected because it allows for network-level filtering, prohibits access to files matching patterns, etc. Since it does not allow renaming directories during an expose mapping, the **py-sandbox** layer handles this.

We have a planned roadmap. Developments will arrive gradually, with no specific order:

- [ ] Guards
  - [X] Control environment variables
  - [X] Control import list
  - [X] Control file and network access
  - [X] Control life cycle of the daemon (restart if necessary)
  - [X] Guard some critical methods in Python (spawn, shell, etc.)
  - [ ] Management of *Denial of Service*
  - [ ] Management of regular expressions
  - [/] Control of `exec()`, `eval()` and `compile()` (the [`eval-*` rules](eval.md))
    - See [here](https://huntr.com/bounties/63ab1cfe-b573-4cf5-a7d3-fb6c957e34b0)
- [ ] OS Compatible
  - [X] Linux
  - [ ] Windows
  - [ ] Mac OS (see https://cursor.com/fr/blog/agent-sandboxing)
- [ ] OS-sandboxes
  - [ ] Basic
    - [X] None
    - [X] sub process
    - [ ] sub interpreter
    - [X] landlock
  - [ ] Sandbox utilities
    - [X] firejail
    - [X] unshare
    - [X] bwrap
    - [ ] Proxy (SOCKS/HTTP over a bound Unix socket + socat, see TODO.md)
  - [ ] Container
    - [X] Docker (--privileged with unshare)
    - [X] podman (--privileged with unshare)
    - [X] kubernetes
    - [ ] Flatpak
    - [ ] rpm-ostree unprivileged
    - [ ] bwrap-oci
    - [ ] gVisor (user space kernel simulation, without docker)
    - [ ] Firecracker
  - [ ] VM
    - [X] Qemu
    - [ ] multipass
    - [ ] lxc
    - [ ] vagrant
  - [ ] micro-VM
    - [ ] [QEMU-microvm](https://www.qemu.org/docs/master/system/i386/microvm.html)
    - [ ] [Firecracker](https://firecracker-microvm.github.io/)
    - [ ] [Fargate](https://aws.amazon.com/fr/fargate/)
    - [ ] [Kata Containers](https://katacontainers.io/) (compatible classical containers management)
    - [ ] [Smolvm](https://korben.info/smolvm-microvm-portable-rust.html)
  - [ ] Others strategies
    - [ ] [container2wasm](https://github.com/container2wasm/container2wasm)
    - [ ] [Cloud Hypervisor](https://github.com/cloud-hypervisor/cloud-hypervisor)
    - [ ] [Cloud morph](https://cloud.morph.so/)
    - [ ] [Agent sandbox](https://agent-sandbox.sigs.k8s.io/docs/getting_started/)
  - [ ] Apple
    - [ ] App Sandbox
    - [ ] sandbox-exec
- [X] New samples
  - [X] [Agnos](https://www.agno.com/docs/guides/agents-sdk)
  - [X] [Crewai](https://www.crewai.com/)
  - [X] [Google ADK](https://google.github.io/adk-docs/)
  - [X] [Microsoft AutoGen](https://www.microsoft.com/en-us/research/project/autogen/)
  - [X] MCP client
  - [X] MCP server
  - [X] [OpenAI Agent SDK](https://developers.openai.com/api/docs/guides/agents-sdk)
  - [X] [Pydantic.ai](https://ai.pydantic.dev/)
  - [X] [Smolagent](https://huggingface.co/docs/smolagents/index)
  - [X] [Strandsagents](https://strandsagents.com)
  - [X] [langchain](https://www.langchain.com/)
  - [X] [langgraph](https://langchain-ai.github.io/langgraph/)
- [ ] Features
  - [ ] Compile a part of code
  - [ ] Propagate the tracability id
  - [ ] Use anyio
  - [ ] Use [Condon JIT](https://docs.exaloop.io/integrations/python/codon-from-python/#using-codonjit)
  - [ ] DevContainer

## Guard some critical methods
A registry of 103 sensitive functions, in six categories (`process-exec`, `process-control`, `privileges`, `threads`, `native`, `introspection`), is denied by default, independently of the import rights granted by `python-import=`.

- Configured with `python-api=ALLOW:<category>|<function>` and `python-api=DENY:<category>|<function>`, resolved by specificity: a function rule beats its category, and `DENY` wins at equal specificity.
- Learning mode records what an application really calls and generates the matching lines.
- Honest limits: `native` and `introspection` are detection and friction, not a barrier — the real barrier is the OS provider.

## New **OS-sandboxes**
Other OS-level sandbox solutions will be integrated, including `Docker` of course.

If your application itself runs in a container, it may not be able to launch another inside (depending on the parameters). This is also the case for solutions relying on Linux *capabilities*.

| Solution          |   Privileges Required   | Docker Socket Mount | Security |  Isolation  |
|-------------------|:-----------------------:|:-------------------:|:--------:|:-----------:|
| Docker-in-Docker  | Yes<br/> (--privileged) |      Optional       |   Low    | High/Medium |
| Podman            |           No            |         No          |   High   |    High     |
| Kubernetes (DinD) |    Yes (privileged)     |      Optional       |   Low    |   Medium    |
| qemu              |           No            |         No          |   High   |    High     |

Different solutions will be proposed (pre-launch of the sandbox in another container, in parallel; use of emulation solutions, like *qemu*, that do not require privileges, etc.).

## Denial of Service
Generated code may never terminate and cause a denial of service. It's not easy to manage this. Indeed, it is easy to identify that a `@sandbox` function is taking too long to respond, but it is very difficult to interrupt it. It is not possible *to kill a thread*, unlike a process. A simple malicious regular expression can be exploited to kill the FastAPI server (see [Catastrophic Backtracking](https://www.regular-expressions.info/catastrophic.html)).

We are considering a solution to identify these situations and kill the offending function if necessary.

## Regular Expressions
Certain regular expression patterns cause problems because they can cause the Python program to become unresponsive. We plan to add a specific filter to refuse the execution of expressions identified as *at risk*.

## Control `exec()`, `eval()` and `compile()`
`exec()`, `eval()` and `compile()` are the functions generally used to execute code generated by an LLM. **py-sandbox** and **os-sandbox** limit the capabilities of that code, but this is not enough: both of them only see a process that has already decided to run the string. We are adding a third level of sandboxing, the **dynamic-code guard**, driven by the `eval-*` rules. A source arriving at one of those three builtins is parsed, checked against a declared sub-language (`eval-syntax=`, `eval-call=`, `eval-attribute=`, `eval-import=`, `eval-magic=`), rewritten so that attribute walks such as `().__class__.__base__.__subclasses__()` are refused while it runs, and executed under an iteration budget, a recursion bound, an allocation ceiling and a timeout the caller can recover from (`eval-timeout=`, `eval-max-iterations=`, `eval-max-alloc=`). The rule family is specified key by key [here](eval.md). The parsing of the `eval-*` rules is implemented; the interception of the three builtins is not yet, so a string handed to them still runs with the full rights of the sandboxed process.

## Compile a part of code
To strengthen security, we are considering compiling a part of the project to make it more difficult to access the standard implementations of Python functions.

## Propagate the tracability id
The protocol break prevents tracking with OpenTelemetry. We want to propagate the necessary information to get a complete trace.


## Dangerous patterns
```
DANGEROUS_PATTERNS = [

    # Dynamic code execution
    r"\b__import__\b",
    r"\bimportlib\b",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bcompile\s*\(",
    r"\btype\s*\(",
    r"\bcallable\s*\(",

    # Builtins/attribute access
    r"\b__builtins__\b",
    r"\b__dict__\b",
    r"\b__class__\b",
    r"\b__globals__\b",
    r"\b__setattr__\b",
    r"\b__getattribute__\b",

    # Introspection
    r"\bglobals\s*\(",
    r"\blocals\s*\(",
    r"\bvars\s*\(",
    r"\bdir\s*\(",
    r"\bgetattr\s*\(",
    r"\bsetattr\s*\(",
    r"\bdelattr\s*\(",
    r"\bhasattr\s*\(",

    # Deserialization
    r"\bpickle\b",
    r"\bmarshal\b",
    r"\bloads\s*\(",

    # File access
    r"\bopen\s*\(",
    r"\binput\s*\(",
    r"\braw_input\s*\(",

    # Shell patterns
    r"\bbash\b",
    r"\bsh\b",
    r"\bcmd\b",
    r"/bin/",
    r"\bsubprocess\b",
    r"\bos\.system\b",
    r"\bpopen\s*\(",
]
```