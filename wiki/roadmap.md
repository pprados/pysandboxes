# Roadmap
The project tests Python API patches and the layered sandbox design. Report reproducible issues with a scenario.

Rules and providers filter network and file access. Their limits differ: Landlock blocks native TCP by default on
ABI v4+, but cannot filter UDP. QEMU enforces `expose-ro` with a read-only 9p export. Python guards handle expose
renaming because OS providers do not rename directories.

Planned work, in no committed order:

- [ ] Guards
  - [X] Control environment variables
  - [X] Control import list
  - [X] Control file and network access
  - [X] Control life cycle of the daemon (restart if necessary)
  - [X] Guard some critical methods in Python (spawn, shell, etc.)
  - [ ] Management of *Denial of Service*
  - [ ] Management of regular expressions
  - [X] Control of `exec()`, `eval()` and `compile()` (the [`eval-*` rules](eval.md))
    - See [here](https://huntr.com/bounties/63ab1cfe-b573-4cf5-a7d3-fb6c957e34b0)
- [ ] OS Compatible
  - [X] Linux
  - [ ] Windows
  - [X] Mac OS
- [ ] OS-sandboxes
  - [X] Basic
    - [X] None
    - [X] sub process
    - [X] ~~sub interpreter~~ (rejected: isolating one interpreter from another is not possible)
    - [X] Landlock
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
    - [X] ~~App Sandbox~~ (rejected: not compatible with the approach)
    - [x] sandbox-exec
    - [ ] Collima
  - [ ] Windows
    - [ ] AppContainer
    - [ ] Windows Sandbox
  - [ ] Network strategies
    - [X] local netfilter and pin DNS
    - [ ] Proxy (SOCKS/HTTP over a Unix socket bound into the sandbox, relayed by socat: 
    filtering by domain, not only by IP)

- [X] Samples
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

## Other **OS-sandboxes**
Other OS-level sandbox solutions will be integrated. Docker and Podman are covered through the `unshare` provider.

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

## Compile a part of code
To strengthen security, we are considering compiling a part of the project to make it more difficult to access the standard implementations of Python functions.

## Propagate the tracability id
The protocol break prevents tracking with OpenTelemetry. We want to propagate the necessary information to get a complete trace.
