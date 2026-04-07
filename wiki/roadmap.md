# Roadmap
This version is a first implementation offered to the community. It allows for testing and demonstrating the validity of the approach.

It ensures that the patches for Python functions are correct and do not cause bugs in applications. If you find a case that presents a problem, open a ticket with a scenario to reproduce it. We will provide a fix as soon as possible.

It also verifies the relevance of the multiple sandbox encapsulation strategy, with only *firejail* for the moment. The latter was selected because it allows for network-level filtering, prohibits access to files matching patterns, etc. Since it does not allow renaming directories during a `bind`, the **py-sandbox** layer handles this.

We have a planned roadmap. Developments will arrive gradually, with no specific order:

- [ ] Guards
  - [X] Control environment variables
  - [X] Control import list
  - [X] Control file and network access
  - [X] Control life cycle of the daemon (restart if necessary)
  - [ ] Guard some critical methods in Python (spawn, shell, etc.)
  - [ ] Management of *Denial of Service*
  - [ ] Management of regular expressions
  - [ ] Control of `exec()` and `eval()`
    - See [here](https://huntr.com/bounties/63ab1cfe-b573-4cf5-a7d3-fb6c957e34b0)
- [ ] OS Compatible
  - [X] Linux
  - [ ] Windows
  - [ ] Mac OS
- [ ] OS-sandboxes
  - [ ] Basic
    - [X] None
    - [X] sub process
    - [ ] sub interpreter
    - [X] langlock
  - [ ] Sandbox utilities
    - [X] firejail
    - [X] unshare
    - [X] bwrap
  - [ ] Container
    - [X] Docker (--privileged with unshare)
    - [X] podman (--privileged with unshare)
    - [X] kubernetes
    - [ ] Flatpak
    - [ ] rpm-ostree unprivileged
    - [ ] bwrap-oci
  - [ ] micro-VM
    - [ ] [Firecracker](https://firecracker-microvm.github.io/)
    - [ ] [Fargate](https://aws.amazon.com/fr/fargate/)
    - [ ] [Kata Containers](https://katacontainers.io/) (compatible classical containers management)
  - [ ] Others strategies
    - [ ] [container2wasm](https://github.com/container2wasm/container2wasm)
    - [ ] [Cloud Hypervisor](https://github.com/cloud-hypervisor/cloud-hypervisor)
    - [ ] [QEMU-microvm](https://www.qemu.org/docs/master/system/i386/microvm.html)
    - [ ] [Cloud morph](https://cloud.morph.so/)
  - [ ] Apple
    - [ ] App Sandbox
    - [ ] sandbox-exec
- [ ] New samples
  - [X] MCP server
  - [X] MCP client
  - [ ] A2A protocol
  - [ ] langchain / langgraph
  - [ ] [Crewai](https://www.crewai.com/)
  - [ ] Google ADK
  - [ ] [Smolagent](https://huggingface.co/docs/smolagents/index)
  - [ ] Pydantic.ai
  - [ ] [Strandsagents](https://strandsagents.com)
- [ ] Features
  - [ ] Compile a part of code
  - [ ] Propagate the tracability id
  - [ ] Use anyio
  - [ ] Use [Condon JIT](https://docs.exaloop.io/integrations/python/codon-from-python/#using-codonjit)
  - [ ] DevContainer

## Guard some critical methods
Certain methods must be rejected, even if the package is authorized (`spawn`, `system`, `sys.exit()`, ....)

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
Certain regular expression patterns cause problems because they can cause the Python program to become unresponsive.
We plan to add a specific filter to refuse the execution of expressions identified as *at risk*.

## Control `exec()` and `eval()`
`exec()` and `eval()` are two functions generally used to execute code generated by an LLM. **py-sandbox** and **os-sandbox** will limit the code's capabilities, but this is not enough.
We plan to add a third level of sandboxing: **exec-sandbox**. A syntactic analysis of the code will be performed before execution. Specific rules will make it possible to forbid, for example, the use of system variables or functions (`__*__`), asynchronous syntax, annotations and automatically add termination checks to all loops, etc.

## Compile a part of code
To strengthen security, we are considering compiling a part of the project to make it more difficult to access the standard implementations of Python functions.

## Propagate the tracability id
The protocol break prevents tracking with OpenTelemetry. We want to propagate the necessary information to get a complete trace.
