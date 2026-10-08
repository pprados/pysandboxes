# Alternatives to PySandboxes: a comparative analysis

*Snapshot of 2026-10-01. Every open-source project was cloned and read at the commit given in
[Sources](#sources-and-commits-analysed); closed services were assessed from their technical documentation,
security pages and independent reviews. Projects move fast: re-check a claim before relying on it.*

PySandboxes is not alone in trying to run code written by a model without handing it the machine. This page
compares it with eighteen other solutions. Some are open-source frameworks you embed, some are open-source
platforms you operate, and some are cloud services you rent. The comparison concentrates on what each
solution actually enforces, how it enforces it, and where its approach differs from ours.

- [Method](#method)
- [The landscape](#the-landscape)
- [Five different bets](#five-different-bets)
- [The network, protocol by protocol](#the-network-protocol-by-protocol)
- [Feature matrix](#feature-matrix)
- [Solution by solution](#solution-by-solution)
- [Primary source examples](#primary-source-examples)
- [Where PySandboxes stands](#where-pysandboxes-stands)
- [Sources and commits analysed](#sources-and-commits-analysed)

## Method

Open projects were assessed from source; closed services from vendor documentation and independent
reviews. Findings were then checked against a common grid of 45 features in twelve families. This helps
surface missing features as well as advertised ones.

Evidence is identified as:

- **code**: read in the source, cited by a link pinned on a commit plus the function or type name;
- **doc**: stated by the vendor's documentation;
- **third party**: an independent review, a disclosure or a CVE.

Absence claims refer to the inspected commit. CVEs were checked against
[NVD](https://nvd.nist.gov), [OSV](https://osv.dev), or the
[GitHub Advisory Database](https://github.com/advisories); items confirmed only by secondary sources are
labelled.

## The landscape

| Solution | Kind | Boundary that holds against hostile native code | Licence |
|---|---|---|---|
| **PySandboxes** | Python framework | Python API patching, inside one OS provider: Landlock, bubblewrap, Firejail, unshare, QEMU | Apache-2.0 |
| [RestrictedPython](https://github.com/zopefoundation/RestrictedPython) | Python library | None. AST rewriting at compile time, guards supplied by the host | ZPL-2.1 |
| [smolagents](https://github.com/huggingface/smolagents) | Agent framework | None for the local AST interpreter. The remote executors delegate to Docker, E2B, Modal or Blaxel | Apache-2.0 |
| [langchain-sandbox](https://github.com/langchain-ai/langchain-sandbox) | Python library, **archived** | Pyodide (CPython compiled to WASM) under Deno permissions | MIT |
| [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) | Agent runtime, self-hosted | Landlock, seccomp-notify broker, seccomp kill-list, then a container or a microVM | Apache-2.0 |
| [Anthropic sandbox-runtime](https://github.com/anthropics/sandbox-runtime) | CLI and library (Claude Code) | bubblewrap and seccomp on Linux, Seatbelt on macOS, plus a host-side proxy | Apache-2.0 |
| [OpenAI Codex sandbox](https://github.com/openai/codex) | Sandbox built into the Codex CLI | Seatbelt on macOS, bubblewrap and seccomp on Linux, restricted token and WFP on Windows, or MXC | Apache-2.0 |
| [microsandbox](https://github.com/superradcompany/microsandbox) | Local microVM runtime | libkrun microVM (KVM, Hypervisor.framework, WHP) | Apache-2.0 |
| [E2B](https://github.com/e2b-dev/E2B) | Platform, SaaS or [self-hosted](https://github.com/e2b-dev/runtime) | Firecracker microVM | Apache-2.0 (open core) |
| [Daytona](https://github.com/daytonaio/daytona) | Platform | Docker container under Sysbox, `--privileged` by default | AGPL-3.0, frozen at v0.190.0 |
| [OpenSandbox](https://github.com/opensandbox-group/OpenSandbox) | Platform, Docker or Kubernetes | runc by default; gVisor, Kata or Firecracker as options | Apache-2.0 |
| [Kubernetes agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) | Kubernetes controller | Whatever the `RuntimeClass` provides: runc, gVisor or Kata | Apache-2.0 |
| [llm-sandbox](https://github.com/vndee/llm-sandbox) | Python library | The Docker, Podman or Kubernetes container, unhardened by default | MIT |
| [Modal Sandboxes](https://modal.com/docs/guide/sandbox-networking) | Cloud service, [open client](https://github.com/modal-labs/modal-client) | gVisor, or a VM on request | Closed platform |
| [Vercel Sandbox](https://vercel.com/docs/sandbox/concepts/firewall) | Cloud service, [open client](https://github.com/vercel/sandbox) | Firecracker microVM | Closed platform |
| [Cloudflare Sandbox](https://developers.cloudflare.com/sandbox/) | Cloud service, [open client](https://github.com/cloudflare/sandbox-sdk) | Container inside a Firecracker microVM | Closed platform |
| [AWS Bedrock AgentCore Code Interpreter](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-tool.html) | Cloud service | Documented as "containerized"; reported as a Firecracker microVM by third parties | Closed |
| [Azure Container Apps dynamic sessions](https://learn.microsoft.com/en-us/azure/container-apps/sessions) | Cloud service | Hyper-V, one VM per session | Closed |
| [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/security/) | Local product for coding agents | A microVM with its own kernel and Docker Engine | Closed |

The isolation primitives these solutions build on are covered in our own provider pages
([Choosing a provider](os-providers.md)) and, for the ones we do not ship, in their upstream documentation:
[gVisor](https://gvisor.dev/docs/), [Firecracker](https://github.com/firecracker-microvm/firecracker),
[Kata Containers](https://katacontainers.io/), [libkrun](https://github.com/libkrun/libkrun),
[Cloud Hypervisor](https://www.cloudhypervisor.org/) and [Pyodide](https://pyodide.org/).

Other services ([Blaxel](https://blaxel.ai), [Northflank](https://northflank.com), Google's Gemini and
Vertex code execution, [Beam](https://github.com/beam-cloud/beta9)) appear in most comparisons. They were
looked at briefly and are not in the grid. Blaxel runs Firecracker with an SNI-based egress proxy, and its
vendor admits that Encrypted Client Hello defeats SNI filtering. Northflank lets the workload choose between
Kata, gVisor and Firecracker, and documents no fine network policy. Google's two code-execution products
have no network access at all and do not name their isolation technology.

## Five different bets

Almost every solution adopts one of five strategies. The differences between solutions come from that choice
far more than from any single feature.

**1. Guard the language.** PySandboxes, RestrictedPython and smolagents' local executor control Python
operations, with different mechanisms. PySandboxes also requires an OS boundary; its Python layer alone
does not hold against compiled code ([Weaknesses](weaknesses.md)).

**2. Confine a process and proxy its traffic.** OpenShell, sandbox-runtime and Codex combine OS restrictions
with an external proxy. Depending on the product, policies can inspect hostnames, HTTP fields, credentials,
or caller identity. This adds network visibility but requires proxy integration.

**3. Put a machine around the code.** MicroVMs and gVisor provide a stronger boundary against hostile native
code, with lifecycle features such as snapshots and persistent volumes. Network defaults vary by product;
the guest may still run with broad privileges.

**4. Orchestrate containers.** agent-sandbox, OpenSandbox, llm-sandbox and Daytona rely on a container
runtime selected by the operator. Their guarantees depend on that runtime and on configured policy.

**5. Run Python as WebAssembly.** langchain-sandbox combines Pyodide and Deno permissions; the project is
archived.

PySandboxes combines language-aware rules with a selectable kernel boundary. It can confine one function and
learn its policy; it does not provide a whole-machine boundary or an L7 proxy.

## The network, protocol by protocol

OpenShell is a good starting point, because it gets one thing exactly right: it decides what to block by
the protocol in use, not by the destination alone. Its seccomp-notify broker sorts every socket at creation.
A UDP socket can only reach the sandbox's own DNS relay or loopback; `connect()` and `sendto()` anywhere else
return `EACCES`. An ICMP socket is never created (`EPROTONOSUPPORT`). On top of that, it adds L7 rules for
REST, GraphQL, JSON-RPC, MCP and WebSocket, behind a TLS interception, and rules on the binary making the
call. So the opening example holds once read in the code: OpenShell does not handle UDP, but it filters at
layer 7, and it grants privileges on more than the network destination alone.

| Solution | Default egress | UDP | ICMP | DNS | Domain rules | Layer 7 | Credentials |
|---|---|---|---|---|---|---|---|
| **PySandboxes** | Deny at the Python layer. At the OS layer: `unshare` and `qemu` set `iptables` to `DROP`; `bwrap` and `firejail` leave only loopback when the profile has no `net=` rule; with `net=` rules under an explicit `restricted-network yes`, `firejail` keeps the host network and warns | `net=` rules, enforced by Python and `iptables`. `landlock` cannot filter UDP | No rule can name it; blocked as a side effect | Names resolved once and pinned into `getaddrinfo` | Name resolved to IPs when the profile is parsed | None | `env=` whitelist; a granted secret enters the sandbox in clear |
| OpenShell | Deny | Only to the DNS relay | Socket never created | Own relay, policy per name | Proxy `CONNECT` + OPA | REST, GraphQL, JSON-RPC, MCP, WebSocket, TLS interception | Placeholders, SigV4, SPIFFE to OAuth2 |
| sandbox-runtime | Open if `allowedDomains` is undefined; the CLI closes it | Impossible: the netns has only loopback | Impossible | Resolved by the proxy after the allow decision | HTTP and SOCKS proxy | Optional TLS interception; domain fronting acknowledged | Masked credentials, SigV4 re-signed |
| Codex | Deny on Linux and macOS; on Windows (restricted token), allow with a WFP deny-list | Blocked by seccomp (Linux Restricted mode) | Blocked on Windows by WFP | Resolved by the proxy, rebinding checked | Optional proxy | Method, path, headers (optional proxy) | Credential broker scoped per host |
| microsandbox | Public internet allowed, private ranges and metadata denied | Relay with session tracking | Echo only, gated by policy | Interception, rebinding defence, pinning | SNI checked against the DNS pin | TLS interception per host, no method or path rules | Placeholders, gated by pin and SNI |
| E2B (open source) | Allow; `allow_out` alone restricts nothing | CIDR only (nftables) | Same as UDP | `8.8.8.8` forced open, even when locked down | SNI and `Host` header, userspace proxy | None in the open-source runtime (cloud only) | Cloud only |
| Daytona | Allow on tiers 3 and 4 | IPv4 CIDR, all protocols together | Same | Not mediated | `domainAllowList` accepted but never enforced | None | None |
| OpenSandbox | Open without `networkPolicy`; deny with one | Timing of DNS leases | IPv6 neighbour discovery only | Own proxy, `NXDOMAIN` on denial | FQDN and wildcards | mitmproxy and addons | Credential vault in the sidecar |
| k8s agent-sandbox | Allow except private ranges and metadata (template) | Like TCP | Left to the CNI | Redirected to public resolvers | None | None | None |
| llm-sandbox | Open (Docker bridge) | Not mediated | Not mediated | Not mediated | None | None | None |
| langchain-sandbox | Deny | No socket layer in Pyodide (not tested) | Same | Not mediated | Deno `--allow-net` host list | None | None |
| Modal | Open | CIDR list "any protocol" (doc) | Not found | Blocked with `block_network` | SNI, port 443 only | None | Header injection per domain |
| Vercel | `allow-all` | Not documented | Not documented | Open under `subnets.allow` (documented) | SNI; domain fronting acknowledged | Matchers on method, path, query and headers; transform, forward or respond; Postgres aware | Header transform, secret never inside |
| Cloudflare | Open (`enableInternet` true); closed, only 80 and 443 leave, through the interception | None | None | Not documented | JavaScript written in the Worker | Anything the Worker code does | In the Worker, on fictitious host names |
| AWS AgentCore | Three modes (sandbox, public, VPC) | DNS leaked in sandbox mode | Not documented | The exfiltration channel | None | None | IAM role |
| Azure dynamic sessions | Deny (`EgressDisabled`) | Not documented | Not documented | Not documented | None | None | Managed identity, off by default |
| Docker Sandboxes | Deny, with presets | Experimental, gated by policy | Blocked | Mediated by the proxy | Allow and deny per host | Host name only | Injected by the proxy |

Three observations follow.

- **UDP and ICMP are where most solutions are vague.** Only OpenShell, sandbox-runtime, Codex on Linux and
  microsandbox give a precise, code-backed answer. Most platforms let any protocol through to an allowed CIDR.
  Others simply do not document it.
- **DNS is the most common leak.** It made AgentCore's "sandbox" mode a command channel
  ([BeyondTrust](https://www.beyondtrust.com/blog/entry/pwning-aws-agentcore-code-interpreter),
  [Unit 42](https://unit42.paloaltonetworks.com/bypass-of-aws-sandbox-network-isolation-mode/), HackerOne report
  3323153). It stays open on
  Vercel when only CIDRs are allowed, and on E2B, by construction, as soon as a domain rule exists.
  PySandboxes pins names to the addresses resolved when the profile is parsed, which closes the TTL drift.
  When a provider uses `iptables`, the sandbox still talks to a resolver ([DNS and iptables](dns.md)).
- **Layer 7 belongs to the proxy-based solutions.** Rules on HTTP method and path exist only behind a proxy:
  OpenShell, Codex, Vercel, Cloudflare (as code), OpenSandbox (through addons) and sandbox-runtime (partly).
  Credential injection, where the real secret never enters the sandbox, is common: nine of the nineteen
  solutions do it fully, three more partly. PySandboxes does neither.

## Feature matrix

`Y` yes, `P` partial, `N` no, `-` not applicable, `?` no source says either way (closed services).
The default egress posture (N1) does not fit a yes/no cell; it is in the
[table above](#the-network-protocol-by-protocol). The policy format (C1) is left out: every solution has
one, as a file, API arguments or code, so the row says nothing.

Columns: **pysb** PySandboxes, **RPy** RestrictedPython, **smol** smolagents, **lcsb** langchain-sandbox,
**OShl** OpenShell, **srt** sandbox-runtime, **Cdx** Codex, **msb** microsandbox, **E2B** E2B,
**Dayt** Daytona, **OSbx** OpenSandbox, **k8s** Kubernetes agent-sandbox, **llms** llm-sandbox,
**Modl** Modal, **Verc** Vercel, **CF** Cloudflare, **AWS** AgentCore, **Azur** Azure dynamic sessions,
**DkSb** Docker Sandboxes.

| ID | Feature | pysb | RPy | smol | lcsb | OShl | srt | Cdx | msb | E2B | Dayt | OSbx | k8s | llms | Modl | Verc | CF | AWS | Azur | DkSb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| I1 | Boundary that holds against hostile native code | P | N | P | Y | Y | Y | P | Y | Y | Y | P | P | P | Y | Y | Y | P | Y | Y |
| I2 | Host-side confinement of the runtime or VMM itself | P | - | ? | N | P | Y | Y | N | P | P | Y | N | - | ? | Y | ? | ? | ? | ? |
| I3 | Choice of isolation backends | Y | Y | Y | N | Y | N | P | N | N | P | Y | Y | Y | Y | N | N | N | N | N |
| N2 | IP/CIDR and port rules | Y | N | N | P | Y | Y | P | Y | P | Y | Y | Y | N | Y | Y | P | P | N | P |
| N3 | UDP handling | P | N | N | ? | Y | Y | P | Y | P | P | P | P | P | P | ? | N | P | ? | P |
| N4 | ICMP handling | N | N | N | ? | N | N | P | P | N | N | P | N | P | N | ? | N | ? | ? | N |
| N5 | DNS mediation | P | N | N | N | Y | Y | P | P | P | N | Y | P | N | P | P | ? | N | ? | Y |
| N6 | SSRF: private ranges, metadata, rebinding | P | N | N | N | Y | Y | Y | Y | Y | N | P | P | N | ? | N | N | ? | ? | Y |
| N7 | Domain/FQDN rules | Y | N | N | P | Y | Y | P | Y | Y | P | Y | N | N | Y | Y | Y | N | N | Y |
| L1 | TLS interception | N | N | N | N | Y | Y | P | Y | N | N | Y | N | N | P | Y | Y | N | N | Y |
| L2 | HTTP method / path / header / query rules | N | N | N | N | P | P | Y | N | N | N | P | N | N | N | Y | Y | N | N | N |
| L3 | Protocol-aware rules beyond HTTP | N | N | P | N | P | N | N | N | N | N | P | P | N | N | P | N | N | N | N |
| L4 | Credential injection / brokering | N | N | P | N | Y | Y | Y | Y | P | N | Y | N | N | Y | Y | Y | N | P | Y |
| L5 | Identity of the caller in network policy | N | N | N | N | Y | P | P | N | N | N | P | P | N | N | N | N | N | N | N |
| F1 | Path-level read/write allow/deny | Y | N | N | Y | Y | Y | Y | Y | N | N | Y | P | P | N | N | N | ? | N | P |
| F2 | Copy-on-write / overlay / ephemeral rootfs | P | - | P | P | Y | N | P | Y | Y | Y | Y | N | P | N | ? | ? | Y | ? | ? |
| F3 | Safe file transfer host and sandbox | P | - | N | - | P | P | P | Y | ? | Y | Y | Y | Y | ? | ? | P | P | ? | P |
| S1 | Syscall filtering | P | N | N | P | Y | P | Y | N | P | N | N | N | P | Y | Y | - | ? | ? | ? |
| S2 | Control of process execution | Y | N | P | Y | P | P | Y | P | P | Y | Y | Y | N | P | N | N | ? | ? | ? |
| S3 | Code runs unprivileged by default (not root, not privileged) | P | - | N | - | P | Y | P | N | P | N | P | N | N | ? | N | ? | ? | ? | ? |
| P1 | Import control | Y | N | Y | N | - | N | N | N | - | - | N | N | N | N | N | N | - | - | - |
| P2 | Sensitive call control beyond imports | Y | N | P | N | - | N | N | N | - | - | N | N | N | N | N | N | - | - | - |
| P3 | Control of `eval` / `exec` / `compile` | Y | P | Y | N | - | N | N | N | - | - | N | N | N | N | N | N | - | - | - |
| P4 | AST restriction / rewriting | Y | Y | Y | N | - | N | N | N | - | - | N | N | N | N | N | N | - | - | - |
| P5 | Per-function granularity | Y | P | P | P | - | - | - | - | - | - | - | - | P | - | - | - | - | - | - |
| C2 | Default deny for everything | Y | P | P | P | Y | P | P | P | N | N | P | N | N | N | N | N | P | P | P |
| C3 | Live update without restart | N | - | N | N | Y | P | P | N | Y | Y | Y | Y | N | Y | Y | Y | ? | Y | Y |
| C4 | Learning / advisor mode | Y | N | N | N | Y | N | P | N | N | N | N | N | N | N | N | N | N | N | N |
| C5 | Formal verification of the policy | N | N | N | N | Y | N | N | N | N | N | N | N | N | N | N | N | N | N | N |
| C6 | Human approval loop for denied actions | P | N | N | N | Y | Y | Y | P | N | N | N | N | N | N | N | N | N | N | N |
| K1 | Environment filtering / secret scrubbing | Y | N | N | Y | Y | Y | Y | P | N | P | Y | N | N | P | N | P | N | N | Y |
| E1 | Cold start / warm pool | P | - | P | N | N | - | P | P | P | Y | Y | Y | Y | Y | Y | ? | ? | Y | ? |
| E2 | Snapshot, pause/resume, fork | N | - | N | P | P | N | N | Y | Y | Y | Y | N | N | Y | Y | P | N | N | N |
| E3 | Persistence across sessions | N | - | P | Y | Y | P | P | Y | Y | Y | P | Y | P | Y | Y | Y | N | N | N |
| R1 | CPU / memory limits | P | N | P | P | P | N | N | Y | Y | Y | Y | Y | P | Y | Y | P | ? | P | P |
| R2 | Timeouts / operation budgets | Y | P | Y | Y | Y | N | Y | Y | Y | Y | P | P | Y | Y | Y | P | Y | Y | N |
| R3 | GPU | N | - | N | N | Y | N | N | N | N | Y | P | Y | N | Y | N | N | ? | P | ? |
| O1 | Decision log, structured denial for the agent | P | P | P | N | Y | Y | P | P | P | Y | Y | P | N | N | N | N | Y | P | P |
| D1 | Linux / macOS / Windows | P | Y | Y | P | Y | P | Y | Y | P | P | P | N | P | - | - | - | - | - | Y |
| D2 | Self-host / SaaS / Kubernetes | P | - | P | P | P | P | P | P | Y | Y | Y | Y | P | Y | Y | Y | Y | Y | Y |
| D3 | Enforcing code is open | Y | Y | Y | Y | Y | Y | Y | Y | P | P | Y | Y | Y | P | P | P | N | N | N |
| G1 | SDKs, MCP, agent frameworks | Y | P | Y | P | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y |
| G2 | Safety of results returned to the host | Y | - | Y | Y | P | - | ? | P | Y | Y | Y | Y | Y | P | ? | P | ? | ? | ? |

Two rows stand out. The language-level rows (P1 to P5) are empty for every solution outside family 1.
Learning or advisor mode (C4) exists only in PySandboxes and OpenShell, and partly in Codex, which adds one
allow rule per human approval.

## Solution by solution

### PySandboxes

- **Bet**: a single declarative `.py-sandboxes` whitelist, recorded by running the real application once in
  learning mode, then enforced twice. Python guards apply it inside the interpreter, and an OS provider
  translates it into a kernel boundary.
- **Strengths**: the only solution that controls imports, a registry of 149 sensitive functions in eight
  categories (`guard_api`), and code arriving as a string (the `eval-*` sub-language: parsed, rewritten, run
  under a budget and a timeout). It is the only one granular to the function (`@sandbox`). Its results are
  unpickled under a guard ([Transport unpickle guard](transport-unpickle-guard.md)). Five interchangeable
  kernel providers are available.
- **Weaknesses**: no layer 7, no TLS interception, no credential brokering. A granted secret enters the
  sandbox in clear. There is no built-in list of private ranges or metadata addresses: the profile author has
  to write the `DENY` rules. No rule can name ICMP. `landlock` cannot filter UDP. A change
  of profile needs a restart. Kernel boundaries exist on Linux and WSL only. The Python layer's known escapes
  are listed in [Weaknesses](weaknesses.md) and the two security assessments.

### RestrictedPython

- **Bet**: rewrite the AST once at compile time, deny any node type without a `visit_` method, and route
  attribute and item access through hooks the host supplies.
- **Strengths**: small (about 2,300 lines), a long history, and a very frank security page: "The guards are
  a second line of defence, not the boundary"
  ([security_considerations.rst](https://github.com/zopefoundation/RestrictedPython/blob/c5066f7d5b2c7538c67c2f8c4635d681c2b325aa/docs/usage/security_considerations.rst#L44-L47)).
- **Weaknesses**: no resource limit, no timeout, no policy on modules, files or network. All of that is left
  to the host. The whitelist only catches new node *types*: the Python 3.15 audit had to add explicit checks
  for lazy imports and comprehension unpacking. Six advisories, all sandbox escapes or leaks, listed on
  [the project's advisories page](https://github.com/zopefoundation/RestrictedPython/security/advisories):
  CVE-2023-37271, CVE-2023-41039, CVE-2024-47532,
  CVE-2025-22153, CVE-2026-55830 and CVE-2026-76825 (`string.Formatter`, fixed in 8.4).

### smolagents

- **Bet**: an AST interpreter written in Python for convenience, and outside services for real isolation.
- **Strengths**: actual operation and loop budgets (`MAX_OPERATIONS`, `MAX_WHILE_ITERATIONS`). A 30 s
  timeout, and a check of every node's return value (`@safer_eval` on `evaluate_ast`).
- **Weaknesses**: it is the default executor. The timeout cannot kill its thread, as its own docstring says.
  `DANGEROUS_MODULES` is never read by the enforcing code; a test only uses it as a list of names. The
  `DockerExecutor` sets no network, capability or memory limit. CVE-2025-5120 and CVE-2025-9959 were sandbox
  escapes. [Issue 2094](https://github.com/huggingface/smolagents/issues/2094) (`ctypes`) is still open.

### langchain-sandbox

- **Bet**: let Deno permissions and WASM do all the work.
- **Strengths**: every permission is closed in the constructor's signature (network, environment, run, FFI).
  Session state round-trips through `dill` as opaque bytes, without the host ever unpickling it.
- **Weaknesses**: archived, and its own README advises against production use. With `allow_read=False`, read
  and write access to the host's `node_modules` is still granted. The Python wrapper pins a published JSR
  package older than the source in the repository. Code and session travel as `argv`, which fails with
  `E2BIG` on large payloads.

### NVIDIA OpenShell

- **Bet**: move the whole trust boundary out of the agent's process and language.
- **Strengths**: per-protocol socket control in a privileged seccomp-notify broker. Policy keyed on the
  binary's identity: path, SHA-256 trusted on first use, ancestor chain, and script paths taken from the
  command line, because "the interpreter (node) is the exe"
  ([`NetworkInput`](https://github.com/NVIDIA/OpenShell/blob/021400be8af471f8669369e679de3e18cf0bd672/crates/openshell-supervisor-network/src/opa.rs#L96-L108)).
  L7 rules for REST, GraphQL, JSON-RPC, MCP and WebSocket, written in Rego. Two checks backed by an SMT solver
  (Z3): a whole-policy exfiltration prover
  ([`openshell-prover`](https://github.com/NVIDIA/OpenShell/blob/021400be8af471f8669369e679de3e18cf0bd672/crates/openshell-prover/src/lib.rs#L4-L44)),
  and a containment check for advisor proposals against an approved baseline
  ([`containment.rs`](https://github.com/NVIDIA/OpenShell/blob/021400be8af471f8669369e679de3e18cf0bd672/crates/openshell-prover/src/containment.rs#L373-L392)).
  A policy advisor: the agent can propose a narrow rule after a denial, and a human approves it. Live policy
  update.
- **Weaknesses**: no ICMP, and UDP only to the DNS relay, by design. No view of what the interpreter does.
  Outside the Docker driver (`network_mode=none`), no network namespace without a route was found: the broker
  alone stands between the workload and raw egress. The containment check does not model GraphQL, JSON-RPC or
  MCP extensions. NVD lists three critical or high CVEs against versions up to 0.0.33:
  [CVE-2026-65093](https://nvd.nist.gov/vuln/detail/CVE-2026-65093) (escape, CWE-427),
  [CVE-2026-65083](https://nvd.nist.gov/vuln/detail/CVE-2026-65083) (provisioning API) and
  [CVE-2026-65091](https://nvd.nist.gov/vuln/detail/CVE-2026-65091) (command injection from a malicious
  gateway). CVE-2026-65086 is reported by the press, not confirmed in a registry.

### Anthropic sandbox-runtime

- **Bet**: wrap an unmodified process tree in bubblewrap and a narrow seccomp filter (Seatbelt on macOS), and
  route every byte through a host-side proxy that filters by host name.
- **Strengths**: no UDP or ICMP at all, because the network namespace has only loopback. SSRF pinning on the
  resolved address, independent of the name list. Masked credentials with
  [AWS SigV4 re-signing](https://github.com/anthropics/sandbox-runtime/blob/5d196e0937ccdd9bedb83b27879a7a2ecd3a0dd2/src/sandbox/aws-sigv4.ts#L4-L11),
  so a secret can sign an allowed request without ever entering the sandbox. A seccomp filter that blocks
  Unix-domain sockets
  ([`seccomp-unix-block.c`](https://github.com/anthropics/sandbox-runtime/blob/5d196e0937ccdd9bedb83b27879a7a2ecd3a0dd2/vendor/seccomp-src/seccomp-unix-block.c#L92-L121)).
- **Weaknesses**: reads are open by default. Network is unrestricted when `allowedDomains` is undefined. The
  vendor acknowledges domain fronting
  ([Claude Code sandboxing](https://code.claude.com/docs/en/sandboxing#security-limitations)). One policy
  per command, no learning mode. One low-severity advisory,
  [CVE-2025-66479](https://github.com/advisories/GHSA-9gqj-5w7c-vx47), fixed in 0.0.16.

### OpenAI Codex sandbox

- **Bet**: the operating system as the only enforcement point. Four native backends are chosen per platform,
  and a decision layer (`execpolicy` prefix rules, human approval) sits above them.
- **Strengths**: a three-mode seccomp filter that also closes an `io_uring` to `AF_VSOCK` bypass
  ([`landlock.rs`](https://github.com/openai/codex/blob/444da310e108da16aaeb18fd790b0ac464f08aca/codex-rs/linux-sandbox/src/landlock.rs#L145-L147)).
  A loopback-only bridge into the network namespace, carrying a per-exec attribution token. An optional proxy
  with method, path and header rules, and a credential broker scoped per host. Allow rules accrue one human
  approval at a time.
- **Weaknesses**: on Windows, the restricted-token backend allows by default with a short deny-list (ICMP,
  DNS, SMB). The proxy is optional. Published incidents hit the decision layer above the sandbox, not the
  kernel boundary: [CVE-2025-59532](https://osv.dev/vulnerability/CVE-2025-59532) (fixed in 0.39.0),
  [CVE-2026-19591](https://nvd.nist.gov/vuln/detail/CVE-2026-19591) (Codex CLI 0.72 to 0.130) and [CVE-2026-19593](https://nvd.nist.gov/vuln/detail/CVE-2026-19593) (`.git/config` read by Codex
  Desktop).

### microsandbox

- **Bet**: one hardware-virtualised microVM, with libkrun on all three operating systems, and a user-space
  network stack (`smoltcp`) on the host.
- **Strengths**: the richest L3/L4 handling of all: a UDP relay with sessions, ICMP limited to echo, DNS
  interception with rebinding defence and DNS-to-IP pinning, SNI checked against the pin, secrets injected
  only when all three agree. The refusal page is written for an LLM to read ("Ask the user to add it...").
- **Weaknesses**: no host-side confinement of the VMM process (no seccomp, Landlock or namespace found in the
  runtime crates), so a hypervisor escape inherits the user's rights. Root inside the guest by default. No
  L7 method or path rules.
  [CVE-2026-61670](https://osv.dev/vulnerability/GHSA-m8f5-rh7h-vgg3) (secrets visible in `/proc/<pid>/cmdline`)
  was fixed in 0.5.10.

### E2B

- **Bet**: a Firecracker microVM per sandbox, restored from a snapshot, plus host-side network mediation.
- **Strengths**: an SSRF check placed exactly between DNS resolution and `connect()` (see
  [Primary source examples](#primary-source-examples)). Pause with a copy-on-write memory export, so the VM resumes
  before its dirty pages are written. Self-hostable on AWS, GCP, Kubernetes or Compose.
- **Weaknesses**: egress is allowed by default, and `allow_out` without `deny_out: ["0.0.0.0/0"]` restricts
  nothing. As soon as a domain rule exists, `8.8.8.8` is open on every protocol and port, and cannot be
  closed. No `jailer`. TLS interception, header injection and bring-your-own-proxy exist only in the closed
  cloud build: the open-source orchestrator rejects them with `Unimplemented`. The legacy v1 API leaves
  `envd` unauthenticated unless `secure` is set.

### Daytona

- **Bet**: Sysbox-hardened Docker containers, with developer ergonomics: fast boot, volumes, snapshots,
  forks.
- **Strengths**: a full machine-like environment. Live network update on paid tiers. A protocol-blind IPv4
  CIDR filter.
- **Weaknesses**: containers run `--privileged` outside GPU and Android sandboxes. No IPv6, DNS or ICMP
  handling, no L7. `domainAllowList` is validated and forwarded by the API but never read by the runner. The
  repository's `main` says the code "moved to a private codebase": the open source is frozen at v0.190.0.
  A batch of advisories in June 2026, all fixed by 0.185.0:
  [CVE-2026-54320](https://nvd.nist.gov/vuln/detail/CVE-2026-54320) (invitation accepted without a verified
  e-mail), [CVE-2026-54321](https://nvd.nist.gov/vuln/detail/CVE-2026-54321) (stale preview-visibility cache),
  [CVE-2026-54324](https://nvd.nist.gov/vuln/detail/CVE-2026-54324) (WebSocket notifications leaked across
  organisations) and [CVE-2026-54323](https://nvd.nist.gov/vuln/detail/CVE-2026-54323) (`git clone` without
  TLS verification). A path traversal, CVE-2026-54319, was rated not exploitable in any released version.

### OpenSandbox

- **Bet**: own the network layer. An egress sidecar does DNS enforcement plus nftables, with FQDN rules and
  mitmproxy.
- **Strengths**: fail closed (`NXDOMAIN` for denied names; the sidecar refuses to start open). A credential
  vault that refuses to activate outside `dns+nft` mode. L7 extensible with mitmproxy Python addons, the
  closest thing in the field to writing a guard by hand. Memory and disk pause/resume on microVMs.
- **Weaknesses**: no sidecar, so no filtering, unless the request carries a `networkPolicy`. The default
  DNS-only mode can be bypassed by direct IP. gVisor, the strongest syscall isolation it offers, is
  incompatible with the sidecar.

### Kubernetes agent-sandbox

- **Bet**: a thin Kubernetes layer (`Sandbox`, `SandboxTemplate`, `SandboxClaim`, `SandboxWarmPool`). Every
  security property is delegated to the `RuntimeClass`, the CNI and admission control.
- **Strengths**: standard objects, warm pools, and a documented fix for a cross-tenant attack through
  Service-selector label spoofing.
- **Weaknesses**: its own threat model says "Agent Sandbox itself does not implement isolation". The
  template's default egress allows everything except private and metadata ranges, and DNS goes to public
  resolvers. A bare `Sandbox` gets none of that. The router's default authoriser is `AllowAll`.

### llm-sandbox

- **Bet**: orchestration convenience over containers you already run.
- **Strengths**: fail-closed tar extraction (`tarfile.data_filter`), written after
  GHSA-crfw-xvcm-hjxj (found on the repository, not yet in the global database). Package-name allow-lists
  per ecosystem, against shell injection.
- **Weaknesses**: root, open network and no limits by default. `runtime_configs` is passed through unfiltered,
  as its own documentation warns. `SecurityPolicy` is a regex that `run()` never calls.

### Modal Sandboxes

- **Bet**: gVisor, or a VM, plus a small set of network settings validated by the client.
- **Strengths**: block, CIDR list or domain list, mutually exclusive and checked before the call. Header
  injection with `$KEY` templates, where the secret never enters the sandbox. GPU, and GPU memory snapshots
  driven by gVisor's checkpoint.
- **Weaknesses**: network open by default. The domain list only covers TLS on port 443, matched by SNI.
  gVisor is a user-space kernel:
  [CVE-2026-96812](https://osv.dev/vulnerability/CVE-2026-96812) (escape through CUSE passthrough) and
  [CVE-2025-2713](https://osv.dev/vulnerability/CVE-2025-2713) affect gVisor itself. Whether they apply to
  Modal's deployment is not known.

### Vercel Sandbox

- **Bet**: a Firecracker microVM and the richest declarative network policy in the field.
- **Strengths**: CIDR and domain rules, matchers on method, path, query and headers, and exactly one action
  per rule: transform, forward or respond. TLS interception only on the hosts that need it, with a CA per
  sandbox. Policy replaced while the sandbox runs. Very candid documentation of its own pitfalls
  ([Firewall](https://vercel.com/docs/sandbox/concepts/firewall)).
- **Weaknesses**: `allow-all` by default. DNS open under `subnets.allow`. Domain fronting acknowledged. UDP
  and ICMP not documented.

### Cloudflare Sandbox

- **Bet**: no policy language at all. The policy is JavaScript in the Worker, and the container sits in a
  Firecracker microVM.
- **Strengths**: as expressive as code can be: rules with state, changed without a redeploy. Credentials
  reached through fictitious host names (`*.sandbox.internal`) that exist only inside the interception.
- **Weaknesses**: nothing validates the policy, and every application rewrites its own. With internet on,
  nothing filters. A cross-tenant leak of residual disk data (dm-thin pools without block zeroing) was fixed
  in September 2026 ([Cloudflare's disclosure](https://blog.cloudflare.com/containers-cross-tenant-vulnerability/)).

### AWS AgentCore, Azure dynamic sessions, Docker Sandboxes

- **AWS AgentCore Code Interpreter**: three network modes and an IAM role, nothing finer. In "sandbox" mode,
  DNS leaked and was turned into a command channel. AWS first called it intended behaviour. The SDK had an
  argument injection, [CVE-2026-16796](https://nvd.nist.gov/vuln/detail/CVE-2026-16796).
- **Azure dynamic sessions**: one Hyper-V VM per session, at the scale of Copilot. Egress is a single on/off
  switch per pool, closed by default. The managed identity is off by default; the documentation warns that
  turning it on lets any code in the session mint tokens.
- **Docker Sandboxes**: a microVM with its own Docker Engine. Deny by default with presets, rules per host,
  credentials injected by the proxy. In 2026, its file-sharing bridge was the weak point:
  [CVE-2026-77179](https://nvd.nist.gov/vuln/detail/CVE-2026-77179) and
  [CVE-2026-79994](https://nvd.nist.gov/vuln/detail/CVE-2026-79994) (symlink TOCTOU escapes), and
  [CVE-2026-17106](https://osv.dev/vulnerability/GO-2026-6253), a bug in the shared `moby/go-archive` library.

## Primary source examples

These source locations support the key distinctions in the comparison:

- [OpenShell network broker](https://github.com/NVIDIA/OpenShell/blob/021400be8af471f8669369e679de3e18cf0bd672/crates/openshell-sandbox/src/network_broker.rs#L840-L850): protocol-specific socket decisions.
- [E2B TCP firewall](https://github.com/e2b-dev/runtime/blob/23f7a0f89dc3645afc5a3026c363bdd6c6f281c1/packages/orchestrator/pkg/tcpfirewall/handlers.go#L163-L184): internal-address rejection before connect.
- [Vercel network policy types](https://github.com/vercel/sandbox/blob/6fc8e16fd606beab8f99546482f11cc40c3e5a8e/packages/vercel-sandbox/src/network-policy.ts#L81-L94): mutually exclusive rule actions.
- [Cloudflare example policy](https://github.com/cloudflare/sandbox-sdk/blob/f9e972a14123bef3b93e9bb337bab6e83419fe7e/examples/outbound-workspace/src/rules.ts#L28-L39): deny, handler, allow, then default deny.
- [RestrictedPython AST transformer](https://github.com/zopefoundation/RestrictedPython/blob/c5066f7d5b2c7538c67c2f8c4635d681c2b325aa/src/RestrictedPython/transformer.py#L500-L519): unknown AST nodes are refused.

## Where PySandboxes stands

**What only PySandboxes does.** No other solution in this survey controls what the Python code itself does.
That means imports, a registry of 149 sensitive functions, and code arriving as a string, which is parsed,
rewritten and run under a budget. It is the only solution that confines one function rather than a process,
a pod or a VM. It is one of two that write their own policy from observed behaviour; OpenShell is the other,
with an advisor rather than a recording. Unlike most solutions, which avoid the problem by never
unpickling, it returns real Python objects from the sandbox, and it unpickles them under a guard. And it lets the user choose among five kernel boundaries, from Landlock with no extra binary up to a
full QEMU VM.

**What the field does better.**

- *A stronger default boundary.* Platforms give every sandbox its own kernel. PySandboxes' strongest option,
  QEMU, is a full VM, not a microVM restored from a snapshot, and the four other kernel providers share the
  host kernel.
- *The network above layer 4.* There is no TLS interception, no method or path rules, no protocol-aware
  rules. Nine solutions match domain rules on the live connection (SNI, `Host`, proxy). PySandboxes resolves names once, when the profile is parsed.
- *Secrets.* The pattern "the secret never enters the sandbox" (placeholders, header injection, SigV4
  re-signing) is widespread. PySandboxes filters the environment, but a granted secret is passed in
  clear.
- *SSRF by default.* Most proxy-based solutions deny private ranges and the cloud metadata address without
  being asked. PySandboxes leaves it to the profile author.
- *Live operations.* Live policy update, human approval of a denied action, a denial structured so the agent
  can understand it, snapshots and warm pools: most of the field has some of these, PySandboxes has none.

**Limits this comparison brings to the fore.**

- No rule can name ICMP. ICMP is only blocked as a side effect, and the `IPPROTO_ICMP` entry of the
  `iptables` generator ([`netfilter.py`](../pysandboxes/netfilter.py)) is never used.
- `landlock` cannot filter UDP, which the [Landlock page](landlock.md) already says.

**Ideas worth borrowing, in decreasing order of value for the effort.**

1. A built-in deny list for private ranges, link-local and metadata addresses, as E2B, microsandbox and
   sandbox-runtime have.
2. Credential placeholders for the network: the sandbox sees a token, and the proxy or the parent swaps it
   for the real value on allowed hosts only.
3. A host-name-aware HTTP proxy for the providers that already run `slirp4netns` or a VM, which the
   [Roadmap](roadmap.md) already lists.
4. OpenShell's idea of tying a network rule to the caller, which PySandboxes could apply at a finer grain
   than anyone else: to the `@sandbox` function, not to the binary.
5. A structured denial addressed to the agent, as OpenShell and microsandbox do, so a model can ask for the
   right rule instead of guessing.

## Sources and commits analysed

| Solution | Analysed at |
|---|---|
| PySandboxes | [pprados/pysandboxes](https://www.github.com/pprados/pysandboxes), `develop` at `bda508f` |
| RestrictedPython | [`c5066f7`](https://github.com/zopefoundation/RestrictedPython/tree/c5066f7d5b2c7538c67c2f8c4635d681c2b325aa) |
| smolagents | [`c30b115`](https://github.com/huggingface/smolagents/tree/c30b115286e000e98711fae5e85993547b73d826) |
| langchain-sandbox | [`fac037c`](https://github.com/langchain-ai/langchain-sandbox/tree/fac037cb46cac3d60aa370feeb1e1f68a1ed91fa) |
| OpenShell | [`021400b`](https://github.com/NVIDIA/OpenShell/tree/021400be8af471f8669369e679de3e18cf0bd672), [docs](https://docs.nvidia.com/openshell/) |
| sandbox-runtime | [`5d196e0`](https://github.com/anthropics/sandbox-runtime/tree/5d196e0937ccdd9bedb83b27879a7a2ecd3a0dd2), [Claude Code sandboxing](https://code.claude.com/docs/en/sandboxing) |
| Codex | [`444da31`](https://github.com/openai/codex/tree/444da310e108da16aaeb18fd790b0ac464f08aca) |
| microsandbox | [`b3843eb`](https://github.com/superradcompany/microsandbox/tree/b3843eb12344c928662323378b9dee113b12f397) (v0.7.5) |
| E2B | SDK [`f713914`](https://github.com/e2b-dev/E2B/tree/f7139140d34ad440e35f4ec7d1bdd183f1b35a6e), runtime [`23f7a0f`](https://github.com/e2b-dev/runtime/tree/23f7a0f89dc3645afc5a3026c363bdd6c6f281c1), [docs](https://e2b.dev/docs) |
| Daytona | v0.190.0 [`01c502b`](https://github.com/daytonaio/daytona/tree/01c502bb1f1ff8f2885d0cd490e043736083dca8) |
| OpenSandbox | [`c7dc78a`](https://github.com/opensandbox-group/OpenSandbox/tree/c7dc78a4090e5de2b9119e9bd93952cae24f87bd) |
| Kubernetes agent-sandbox | [`82d410e`](https://github.com/kubernetes-sigs/agent-sandbox/tree/82d410efd5a279e887cdcf8c01e742a345fef63d) |
| llm-sandbox | [`7361f5e`](https://github.com/vndee/llm-sandbox/tree/7361f5e5ca06b5597f977f13efbe859f481cb01e) |
| Modal | client [`83cd277`](https://github.com/modal-labs/modal-client/tree/83cd27748d1fc0ac6adbf5acc8e9a3bfbf85208e), [networking](https://modal.com/docs/guide/sandbox-networking), [security](https://modal.com/docs/guide/security) |
| Vercel | client [`6fc8e16`](https://github.com/vercel/sandbox/tree/6fc8e16fd606beab8f99546482f11cc40c3e5a8e), [firewall](https://vercel.com/docs/sandbox/concepts/firewall) |
| Cloudflare | client [`f9e972a`](https://github.com/cloudflare/sandbox-sdk/tree/f9e972a14123bef3b93e9bb337bab6e83419fe7e) (1.0 preview), [Containers outbound traffic](https://developers.cloudflare.com/containers/platform-details/outbound-traffic) |
| AWS AgentCore | [AgentCore documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-tool.html), [BeyondTrust](https://www.beyondtrust.com/blog/entry/pwning-aws-agentcore-code-interpreter), [Unit 42](https://unit42.paloaltonetworks.com/bypass-of-aws-sandbox-network-isolation-mode/) |
| Azure dynamic sessions | [Container Apps sessions](https://learn.microsoft.com/en-us/azure/container-apps/sessions) |
| Docker Sandboxes | [Docker Sandboxes documentation](https://docs.docker.com/ai/sandboxes/security/) |

CVE numbers were checked on 2026-10-01. Only CVE-2026-65086 (OpenShell) was seen in secondary sources alone,
and it is quoted as such.
