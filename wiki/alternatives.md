# Alternatives to PySandboxes

*Snapshot: 2026-10-01 for the other solutions, 2026-11-13 for PySandboxes (release 0.12.0, commit `2601d77b`).
Open-source projects were checked at the commits listed in
[Sources](#sources-and-commits-analysed). Closed services were assessed from vendor documentation, security
pages, and independent reviews. The PySandboxes rows, cells and paragraphs were refreshed on 2026-11-13 from
the code of this repository. The other solutions got one web search each that day, and a primary page of each (README, documentation page or releases
page) was read and compared with the text, with uneven depth: for microsandbox, RestrictedPython and
AWS AgentCore the pages read gave nothing new on network or isolation; the discrepancies found are
corrected in the sections concerned (see the end of [Sources](#sources-and-commits-analysed)). The
source-code analysis, the analysed commits and the 45-feature matrix are still those of 2026-10-01 and may
be out of date. Verify claims before relying on them; projects
change.*

This page compares PySandboxes with eighteen solutions: embeddable frameworks, self-hosted platforms, and cloud
services. It focuses on enforced controls, implementation, and security boundaries.

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
| **PySandboxes** | Python framework | Python API patching, inside one OS provider: Landlock, bubblewrap, Firejail, unshare, QEMU (full VM or microvm), gVisor, smolvm (micro-VM), macOS Seatbelt, or a Windows AppContainer | Apache-2.0 |
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
| [llm-sandbox](https://github.com/vndee/llm-sandbox) | Python library | The Docker, Podman or Kubernetes container, unhardened by default; the README of 2026-11-13 adds Bubblewrap, NsJail and Windows backends not analysed here | MIT |
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
| **PySandboxes** | Deny at the Python layer. At the OS layer: `unshare` and `qemu` set `iptables` to `DROP`; `bwrap` and `firejail` leave only loopback when the profile has no `net=` rule; with `net=` rules under an explicit `restricted-network yes`, `firejail` keeps the host network and warns. `landlock` denies native TCP bind/connect by default on ABI v4+; the provider is unavailable below ABI v4 | `net=` rules, enforced by Python and `iptables`. `landlock` cannot filter native UDP | No rule can name it; blocked as a side effect | `net-resolve=pinned` (the value without the key): names resolved once and pinned into `getaddrinfo` and `/etc/hosts`. `net-resolve=runtime`: a filtering resolver on the host answers only the names a rule allows and opens the addresses for the TTL | `pinned`: name resolved to IPs at start. `runtime`: name resolved when the program asks; one address is shared by every name behind it | None | `env=` whitelist; a granted secret enters the sandbox in clear |
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
  PySandboxes pins names to the addresses resolved at start (`net-resolve=pinned`), which closes the TTL
  drift but refuses a rotating name; `net-resolve=runtime` follows the name instead. When a provider uses
  `iptables`, the sandbox still talks to a resolver, and the filter always accepts UDP port 53 to it:
  DNS stays a low-rate exfiltration channel under every provider that has its own network namespace
  ([DNS and iptables](dns.md), [Weaknesses](weaknesses.md#os-provider-limitations)).
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
| I3 | Choice of isolation backends | Y | Y | Y | N | Y | P | P | N | N | P | Y | Y | Y | Y | N | N | N | N | N |
| N2 | IP/CIDR and port rules | Y | N | N | P | Y | Y | P | Y | P | Y | Y | Y | N | Y | Y | P | P | N | P |
| N3 | UDP handling | P | N | N | ? | Y | Y | P | Y | P | P | P | P | P | P | ? | N | P | ? | P |
| N4 | ICMP handling | N | N | N | ? | N | N | P | P | N | N | P | N | P | N | ? | N | ? | ? | N |
| N5 | DNS mediation | P | N | N | N | Y | Y | P | P | P | N | Y | P | N | P | P | ? | N | ? | Y |
| N6 | SSRF: private ranges, metadata, rebinding | P | N | N | N | Y | Y | Y | Y | Y | N | P | P | N | ? | N | N | ? | ? | Y |
| N7 | Domain/FQDN rules | Y | N | N | P | Y | Y | P | Y | Y | P | Y | N | N | Y | Y | Y | N | N | Y |
| L1 | TLS interception | N | N | N | N | Y | Y | P | Y | N | N | Y | N | N | P | Y | Y | N | N | Y |
| L2 | HTTP method / path / header / query rules | N | N | N | N | P | P | Y | N | N | N | P | N | N | N | Y | Y | N | N | N |
| L3 | Protocol-aware rules beyond HTTP | N | N | P | N | P | N | P | N | N | N | P | P | N | N | P | N | N | N | N |
| L4 | Credential injection / brokering | N | N | P | N | Y | Y | Y | Y | P | N | Y | N | N | Y | Y | Y | N | P | Y |
| L5 | Identity of the caller in network policy | N | N | N | N | Y | P | P | N | N | N | P | P | N | N | N | N | N | N | N |
| F1 | Path-level read/write allow/deny | Y | N | N | Y | Y | Y | Y | Y | N | N | Y | P | P | N | N | N | ? | N | P |
| F2 | Copy-on-write / overlay / ephemeral rootfs | P | - | P | P | Y | N | P | Y | Y | Y | Y | N | P | N | ? | ? | Y | ? | ? |
| F3 | Safe file transfer host and sandbox | P | - | N | - | P | P | P | Y | ? | Y | Y | Y | Y | ? | ? | P | P | ? | P |
| S1 | Syscall filtering | P | N | N | P | Y | P | Y | N | P | N | P | N | P | Y | Y | - | ? | ? | ? |
| S2 | Control of process execution | Y | N | P | Y | P | P | Y | P | P | Y | Y | Y | N | P | N | N | ? | ? | ? |
| S3 | Code runs unprivileged by default (not root, not privileged) | P | - | N | - | P | Y | P | N | P | N | P | N | P | ? | N | ? | ? | ? | ? |
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
| K1 | Environment filtering / secret scrubbing | Y | N | N | Y | Y | Y | Y | P | N | P | Y | N | P | P | N | P | N | N | Y |
| E1 | Cold start / warm pool | P | - | P | N | N | - | P | P | P | Y | Y | Y | Y | Y | Y | ? | ? | Y | ? |
| E2 | Snapshot, pause/resume, fork | N | - | N | P | P | N | N | Y | Y | Y | Y | P | P | Y | Y | P | N | N | N |
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

Seven cells were changed on 2026-11-13. E2 for agent-sandbox went from `N` to `P`: at `13470fe` the `Sandbox`
API has an `operatingMode` of `Suspended`, with a `Suspended` condition that turns true once the backing Pod is
terminated, and `volumeClaimTemplates` keep state on volumes; the memory and process state are not kept. E2 for
llm-sandbox went from `N` to `P`: `docker.py` at `abdddb2` takes a
`commit_container` option that commits the container to a new image, which saves the filesystem but not the
process or memory state. L3 for Codex went from `N` to `P`: in `network-proxy/src` at `69231e1`,
decisions and audit events are keyed by a `NetworkProtocol` (`Http`, `HttpsConnect`, `Socks5Tcp`, `Socks5Udp`)
and a limited mode keeps SOCKS5 UDP and non-HTTPS SOCKS5 TCP blocked, which is protocol-aware handling beyond
HTTP, though not a rule language for those protocols. S3 and K1 for llm-sandbox went from `N` to `P`, because its local
Bubblewrap backend (`bubblewrap.py` at `abdddb2`) runs with `--unshare-user` and `--cap-drop ALL` and starts
from `--clearenv`, while its container backend still starts as root. I3 for sandbox-runtime went from `N` to `P`, because its code at
`0bbebed0` offers a Windows backend choice (`windows.backend` set to `'mxc'`); on Linux and macOS it has one
backend each. S1 for OpenSandbox went from `N` to `P`: at `e564cd1`, `components/execd/pkg/isolation` and
`configs/isolation.example.toml` describe a seccomp denylist of about thirty syscalls (`mount`, `ptrace`,
`bpf`...) that the file calls always active by default for execd isolation; whether every sandbox goes through
execd isolation was not checked, hence `P`. A keyword search of the other clones found no change to the S1
cells of microsandbox, Daytona and agent-sandbox (the latter only passes `seccompProfile` through its CRD).
The microsandbox column was re-read against the code at `28bdced5` for I2, I3, N2, C3, L5, S1, R1, R2, R3, E2 and
D1 (no libkrun alternative, `Destination::Cidr` rules, no live policy update, no GPU or caller-identity code,
a per-job `timeout_ms`, fork and snapshot with `--cow-mem` in the README, `cfg(target_os = "windows")` code in
the metrics crate) and none of those cells changed. The OpenSandbox column was re-read at `e564cd1` for N2, N3,
N4, L2, C6, R1, R2, R3, D1 and E3 and none of those cells changed either: the egress `EgressRule` carries a
target, ports and port ranges but no method, path or header matcher (hence `P` for L2, which rests on
mitmproxy addons), the nftables manager says UDP and QUIC rely on DNS-driven refresh, the create request
takes `timeout_seconds` up to 10800 and `cpu`, `memory` and `gpu` limits, no approval flow appears in the
egress code, and the execd build skips non-Linux targets. The E2B column was re-read in `e2b-dev/infra` at
`ee78f06` for N3, L1, L4, C3, R3 and S1 and none of those cells changed: UDP outside port 53 has an operator
mode (`NonDNSUDPMode`), the interception and proxy hooks are stubs in the open-source build, `update_network.go`
replaces the policy at run time, no GPU code appears in the orchestrator or the API, and `seccomp` appears only
around helper tools (`debugfs`, template builds), not around the guest, so S1 `P` rests on Firecracker itself
and was not confirmed in this repository. The Codex column was also read for L2, N3, C6 and R1: the proxy has an `allowed_methods` check in `mitm.rs` and
`methods` and `path_prefixes` rules in its SOCKS5 tests, `enable_socks5_udp` is on by default, a
`NetworkPolicyDecision` has `Deny` and `Ask`, and a search for `RLIMIT`, `cgroup` and `setrlimit` finds no
resource limits; those cells stand. The sandbox-runtime column was read at `0bbebed0` for L1, L3, C3, C6, N6, O1, R1 and R2, and
none of those cells changed: `mitm-ca.ts` and a `tlsTerminate` option back L1, `resolved-address-guard.ts`
backs N6, `SandboxAskCallback` takes only a host and a port (so L3 stays `N`: the decision does not depend on
the protocol), `SandboxViolationStore` and the two violation monitors back O1, `updateConfig()` and per-command
lists leave C3 at `P`, and the only timeouts found are internal to the proxies, with no CPU or memory limits.
The OpenShell column was read at `7cfa0c09` for I3, C4, C5, C6, O1, R1 and R3 and none of those cells changed: five
compute drivers back I3, a policy-advisor skill and an `openshell-prover` crate back C4 and C5, a manual or
automatic `approval_mode` and `prover_delta` audit events back C6, `openshell-ocsf` backs O1, `openshell-vfio`
backs R3, and R1 stays `P` because only a PID limit was found, not memory or CPU. The agent-sandbox column was also read for E1, E3, R2 and S3: a `SandboxWarmPool` type with `Recreate` and
`OnReplenish` update strategies backs E1, `volumeClaimTemplates` back E3, a `Lifecycle` with a `shutdownTime`
backs R2, and a search for `runAsNonRoot` and `runAsUser` in the controllers finds nothing, so S3 stays `N`.
The llm-sandbox column was also read for E1, R1, R2, S1 and O1: a `pool` package with Docker, Kubernetes and
Podman pools backs E1, `default_timeout` and `execution_timeout` back R2, limits only through the pass-through
`runtime_configs` keep R1 at `P`, a `security/seccomp.py` module backs S1, and the policy's issue severities
are not applied by `run()`, so O1 stays `N`. The smolagents column was read at
`96f33fa` for P1, P2, P3, P4, R1 and E3 and none of those cells changed: `authorized_imports` with
`check_import_authorized` backs P1, `DANGEROUS_FUNCTIONS` (`builtins.eval`, `exec`, `compile`, `globals`,
`locals`, `__import__`, `os.system`...) backs P3, an AST walk in `evaluate_ast` backs P4, the dunder guard is a
replacement `getattr` only (`nodunder_getattr`), which keeps P2 at `P`, and the only resource setting found on
the remote executors is the Blaxel `memory` argument and a 5-minute Docker kernel timeout. No other cell was
re-derived from code. Two rows stand out. The language-level rows (P1 to P5) are empty for every solution outside family 1.
Learning or advisor mode (C4) exists only in PySandboxes and OpenShell, and partly in Codex, which adds one
allow rule per human approval.

## Solution by solution

### PySandboxes

- **Bet**: a single declarative `.py-sandboxes` whitelist, recorded by running the real application once in
  learning mode, then enforced twice. Python guards apply it inside the interpreter, and an OS provider
  translates it into a kernel boundary.
- **Strengths**: the only solution that controls imports, a registry of 152 sensitive functions in eight
  categories (`guard_api`), and code arriving as a string (the `eval-*` sub-language: parsed, rewritten, run
  under a budget and a timeout). It is the only one granular to the function (`@sandbox`). Its results are
  unpickled under a guard ([Transport unpickle guard](transport-unpickle-guard.md)). Eight interchangeable
  Linux providers are available (`landlock`, `bwrap`, `firejail`, `unshare`, `qemu`, `qemu-microvm`, `gvisor`
  and `smolvm`), plus `sandbox-exec` on macOS and AppContainer on Windows. The VM providers need `/dev/kvm`
  for a boundary claim. It passed the Windows VM matrix as administrator and as standard user.
- **Weaknesses**: no layer 7, no TLS interception, no credential brokering. A granted secret enters the
  sandbox in clear. There is no built-in list of private ranges or metadata addresses: the profile author has
  to write the `DENY` rules. No rule can name ICMP. `landlock` cannot filter UDP. A change
  of profile needs a restart. The kernel-backed providers exist on Linux and WSL only. AppContainer provides
  the Windows OS boundary. The Python layer's known escapes
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
  CVE-2025-22153, CVE-2026-55830 (guard hooks shadowed through positional-only arguments, fixed in 8.3.0) and
  CVE-2026-76825 (`string.Formatter`, fixed in 8.4.0, dated 2026-07-10 in the changelog). A pull request opened
  on 2026-11-05 proposes a 5.4.post1 security release of the 5.4 line; a web search on 2026-11-13 does not
  show whether it was merged. Recheck of the code at commit `9d7aeb26` (2026-11-04, read 2026-11-13):
  `Guards.py` refuses `string.Formatter` (`NotImplementedError('string.Formatter is not safe')`) and
  `transformer.py` iterates `posonlyargs`, which matches the two 2026 fixes. Only these two spots were read.

### smolagents

- **Bet**: an AST interpreter written in Python for convenience, and outside services for real isolation.
- **Strengths**: actual operation and loop budgets (`MAX_OPERATIONS`, `MAX_WHILE_ITERATIONS`). A 30 s
  timeout, and a check of every node's return value (`@safer_eval` on `evaluate_ast`).
- **Weaknesses**: it is the default executor. The timeout cannot kill its thread, as its own docstring says.
  `DANGEROUS_MODULES` is never read by the enforcing code; a test only uses it as a list of names. The
  `DockerExecutor` sets no network, capability or memory limit. CVE-2025-5120 and CVE-2025-9959 were sandbox
  escapes. [Issue 2094](https://github.com/huggingface/smolagents/issues/2094) (`ctypes`) was open on 2026-10-01. A search on 2026-11-13 also lists CVE-2026-4963 (code injection in
  `evaluate_augassign`, `evaluate_call` and `evaluate_with`, published 2026-03-27, an incomplete fix of
  CVE-2025-9959; the sources give a severity of 10 and of 5.3) and CVE-2026-2654 (SSRF through `requests.get`
  and `requests.post`, up to 1.24.0). No patched version was confirmed for either. Recheck of the code at commit `96f33fa` (2026-10-06, read
  2026-11-13): `MAX_OPERATIONS` and `MAX_WHILE_ITERATIONS` are still defined in `local_python_executor.py`;
  `DANGEROUS_MODULES` (ten names, without `ctypes`) is still referenced only by a test; the timeout still
  raises `ExecutionTimeoutError` from a worker thread it cannot kill; and a keyword search of
  `remote_executors.py` finds no `network_mode`, `mem_limit`, `cap_drop`, `read_only`, `security_opt` or
  `pids_limit`. The remote executors are still `E2BExecutor`, `DockerExecutor`, `ModalExecutor` and
  `BlaxelExecutor`. Issue 2094 was still open when fetched on 2026-11-13, with a suggested fix that adds
  `ctypes` to the list; the repository has no commit after 2026-10-06 in the clone read.

### langchain-sandbox

- **Bet**: let Deno permissions and WASM do all the work.
- **Strengths**: every permission is closed in the constructor's signature (network, environment, run, FFI).
  Session state round-trips through `dill` as opaque bytes, without the host ever unpickling it.
- **Weaknesses**: archived by its owner on 2026-01-14 (GitHub, checked 2026-11-13 through a web search), and
  its own README advises against production use. [Cyera](https://www.cyera.com/research/sandcastles-not-sandboxes-how-one-architectural-flaw-exposed-seven-products)
  reports a `ctypes` path to `system()` that Emscripten's syscall emulation serves outside Deno's `allow_run`;
  only that write-up ties the archiving to the disclosure, and it was read as a search summary, not in full. With `allow_read=False`, read
  and write access to the host's `node_modules` is still granted. The Python wrapper pins a published JSR
  package older than the source in the repository. Code and session travel as `argv`, which fails with
  `E2BIG` on large payloads. Recheck of the clone at commit `fac037c` (2026-01-14, the archived tip, read
  2026-11-13): `libs/sandbox-py/langchain_sandbox/pyodide.py` still builds the six Deno flags `--allow-env`,
  `--allow-read`, `--allow-write`, `--allow-net`, `--allow-run` and `--allow-ffi` from constructor settings,
  with `node_modules` forced as the default read and write path, which matches the points above; it still
  pins `jsr:@langchain/pyodide-sandbox@0.0.4`. A keyword search for `ctypes` and `system(` finds nothing in the
  repository's own code, which is consistent with a flaw that lives in the Emscripten layer, not here.

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
  gateway). CVE-2026-65086 is now listed with the others in
  [NVIDIA's August 2026 security bulletin](https://nvidia.custhelp.com/app/answers/detail/a_id/5872) (65083,
  65085, 65086, 65091, 65092 and 65093, fixed in v0.0.34), as seen in a search result on 2026-11-13; the
  bulletin was not read in full. The same search lists releases up to v0.1.6 (v0.1.5 on 2026-10-20), later
  than the commit analysed here. The project README, read the same day, announces "a stable release cadence,
  new isolation primitives, an expanded extension surface" for 0.1.x, SDKs in Python, TypeScript, Go and Rust,
  and a move of the code to the `ai-openshell` organisation with governance going to the CNCF. The new
  isolation primitives are not named there, so the Landlock and seccomp description above was not rechecked
  against 0.1.x. A keyword search of the crates at `main` commit `7cfa0c09` (2026-11-13) still finds
  `network_broker.rs` in `openshell-sandbox` and the words `seccomp` and `landlock` in that crate's sources and
  README, and a `rego` policy in `openshell-supervisor-network`; its `crates` directory now lists compute
  drivers for Docker, Kubernetes, Podman, a VM and `mxc`, credential drivers (`vault`, `db-credstore`,
  `kubernetes-secrets`), a `openshell-prover` crate with its CLI, an `openshell-vfio` crate that binds GPUs
  through sysfs, an `openshell-ocsf` crate for structured audit events and a Podman driver that sets a default
  per-sandbox PID limit of 2048 (`DEFAULT_SANDBOX_PIDS_LIMIT`). Only crate names and the places named here were
  read.

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
  ([Claude Code sandboxing](https://code.claude.com/docs/en/sandboxing#security-limitations)). The README
  read on 2026-11-13 now documents per-command network allow lists (`registerCommandNetworkLists`, added on
  top of the configured list for the life of one command) and `:port` suffixes on domain entries, so "one
  policy per command" no longer holds for the network; the filesystem policy is still global. It also
  states that all network access is denied by default and that an empty `allowedDomains` means no network,
  which the analysed commit did not do when the field was undefined; whether the library now closes that case
  was not checked in code. No learning mode. One low-severity advisory,
  [CVE-2025-66479](https://github.com/advisories/GHSA-9gqj-5w7c-vx47), fixed in 0.0.16. The releases page,
  read on 2026-11-13, lists v0.0.81 (20 October) as the newest, a release whose notes say every change is on
  Windows; the project is still labelled a research preview, and the commit analysed here predates all of it. A recheck of the code at `0bbebed0`
  (2026-11-12, 2026-11-13) still finds `seccomp-unix-block.c`, `aws-sigv4.ts` and the credential-masking
  modules, and `sandbox-manager.ts` still tells an undefined `allowedDomains` apart from an empty list
  (`runtimeConfig.network.allowedDomains !== undefined`), which fits the matrix cell "open if undefined". It
  also shows a Windows backend choice (`windows.backend` set to `'mxc'`) that the 2026-10-01 text does not
  mention. Only these spots were read.

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
  Desktop). A search on 2026-11-13 adds CVE-2026-19592 (a repo-local `core.fsmonitor` helper run outside the
  command sandbox, published 2026-09-01), two flaws without a CVE called Heapjack and Overpatch (fixed in Codex
  CLI 0.149.0, 2026-08-21) and seven escapes across several agents disclosed by Pillar Security in July 2026
  (Codex CLI fixed in 0.95.0). They again concern the layer above the kernel boundary, not Seatbelt, bubblewrap
  or seccomp. Recheck of the code at `openai/codex` commit `69231e1` (2026-11-13): the filter is now in
  `codex-rs/linux-sandbox/src/seccomp.rs`, no `landlock.rs` remains in that crate and a comment there calls the
  Landlock filesystem backend legacy, with bubblewrap used for filesystem-restricted policies. It still has
  three network modes (`Restricted`, `ProxyRouted`, `VmSocketRestricted`), denies `io_uring_setup`,
  `io_uring_enter` and `io_uring_register` with a comment that `io_uring` can create `AF_VSOCK` sockets
  without a `socket()` call, and outside the `VmSocketRestricted` mode also denies `ptrace`,
  `process_vm_readv`, `process_vm_writev` and `request_key`. The crate has grown a managed TCP relay
  (`managed_tcp.rs`, `proxy_routing.rs`) and the repository has `mxc-sandbox`, `windows-sandbox-rs`,
  `windows-sandbox-service` and `network-proxy` crates. In `network-proxy/src`, `attribution.rs` defines the
  per-exec attribution token (`CODEX_NETWORK_PROXY_ATTRIBUTION`, a framed header of at most 128 bytes with a
  3 s timeout), and the directory also holds `credential_broker.rs`, `aws_sigv4.rs`, `secret_substitution.rs`,
  `mitm.rs` and `domain_matcher.rs`, which fit the claims about the token, the credential broker and the
  optional proxy. The method, path and header rules themselves were located by file name only and not read.

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
- **Recheck, 2026-11-13, at commit `28bdced5` (2026-11-12)**: a keyword search of the Rust crates, not a full
  read, still finds no `seccomp`, `landlock`, `pivot_root`, `sandbox_init` or `unshare(` anywhere, so the
  absence of host-side confinement of the VMM still holds. The network crate still carries an ICMP relay
  (`engine/icmp/relay.rs`), a DNS engine that mentions SNI, a secrets handler that checks it
  (`engine/secrets/handler.rs`), a TCP deny path (`engine/tcp/deny.rs`) and a `smoltcp` fork (`msb_smoltcp`
  0.14.0). The search for L7 method or path rules finds nothing in the network crate. The claims about the UDP
  relay sessions, the ICMP echo limit and the rebinding defence were not re-read.

### E2B

- **Bet**: a Firecracker microVM per sandbox, restored from a snapshot, plus host-side network mediation.
- **Strengths**: an SSRF check placed exactly between DNS resolution and `connect()` (see
  [Primary source examples](#primary-source-examples)). Pause with a copy-on-write memory export, so the VM resumes
  before its dirty pages are written. Self-hostable on AWS, GCP, Kubernetes or Compose.
- **Weaknesses**: egress is allowed by default, and `allow_out` without `deny_out: ["0.0.0.0/0"]` restricts
  nothing. As soon as a domain rule exists, `8.8.8.8` is open on every protocol and port, and cannot be
  closed. No `jailer`. TLS interception, header injection and bring-your-own-proxy exist only in the closed
  cloud build: the open-source orchestrator rejects them with `Unimplemented`. The legacy v1 API leaves
  `envd` unauthenticated unless `secure` is set. The current E2B documentation (read on 2026-11-13) confirms that
  `8.8.8.8` gets all traffic, not only DNS, once a domain is allowed, but now adds a `dnsServers` option: a
  list of up to ten IPv4 addresses replaces it, and an empty list allows no DNS server, so "cannot be closed"
  describes the analysed commit, not the current API. The code agrees: in `e2b-dev/infra` at `ee78f06`
  (2026-11-13), `buildEgressConfig` in `packages/api/internal/orchestrator/create_instance.go` takes
  `dnsServers`, uses `DefaultNameserver = "8.8.8.8"` (`packages/shared/pkg/sandbox-network/firewall.go`) only
  when it is nil, and `update_network.go` passes the field on a running sandbox. The generated API also carries
  per-host `rules`. The open-source orchestrator still carries the bring-your-own-proxy and interception
  hooks as stubs: in `orchestrator/pkg/tcpfirewall/proxy.go`, `SupportsBYOP()` returns `false`, `CABundle()`
  returns an empty string and `HeadFilterRules()` returns nothing, and `server/sandboxes.go` refuses a start
  that asks for an egress proxy when `SupportsBYOP()` is false, behind the `BYOPProxyEnabledFlag` feature flag;
  so the cloud-only split above still holds in the code, in this form. The firewall also gained a
  `NonDNSUDPMode` (`off`, `count` or `drop` for guest UDP outside port 53) and four chain postures (`default`,
  `rules`, `byop`, `isolated`). A keyword search for `jailer` still finds nothing. The same page
  describes `allowInternetAccess: false` as `denyOut` of `0.0.0.0/0`, a policy replaced at run time with
  `updateNetwork()`, per-host header injection in public beta and a bring-your-own proxy in private beta, which
  fits the cloud-only split above. It also warns that a blocked TCP connection can look successful from inside
  the sandbox. A third-party project reports numbered addresses getting through; that claim is not confirmed.

### Daytona

- **Bet**: Sysbox-hardened Docker containers, with developer ergonomics: fast boot, volumes, snapshots,
  forks.
- **Strengths**: a full machine-like environment. Live network update on paid tiers. A protocol-blind IPv4
  CIDR filter.
- **Weaknesses**: containers run `--privileged` outside GPU and Android sandboxes. No IPv6, DNS or ICMP
  handling, no L7. `domainAllowList` is validated and forwarded by the API but never read by the runner. The
  repository's `main` says the code "moved to a private codebase": the open source is frozen at v0.190.0.
  Its README, read on 2026-11-13, describes sandboxes as having "a dedicated kernel, filesystem, network
  stack", without naming the isolation technology, which is not what the Sysbox container above shows.
  The code of the last public release was read again on 2026-11-13 from the tag `v0.190.0`
  (`01c502bb`, 2026-06-23), since `main` now holds only a README and images: `container_configs.go` still sets
  `Privileged: gpuIndex == nil`, so every sandbox without a GPU is privileged; the docs of that tag still say
  Daytona "uses Sysbox as its container runtime" (`security-exhibit.mdx`, with `sysbox-runc` as the default
  `CONTAINER_RUNTIME`); and `domainAllowList` appears in the API, the database migration and the runner adapter,
  but in the runner only in its generated Swagger files, never in Go logic, which matches the claim above.
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
  incompatible with the sidecar. The project now lives under `opensandbox-group` and its releases page, read on
  2026-11-13, marks 1.2.1 as the latest release (1.1.0 of 2026-09-21 was the first umbrella release). A search
  of the same day describes 1.2.0, which adds port-scoped rules to the classic profile (the fast
  profile rejects them) and rejects `networkPolicy` for the Docker network modes `none`, `pasta` and
  `slirp4netns`. An upstream issue (#2329, opened 2026-10-21) reported established TCP sessions surviving a
  tightened policy on server 0.2.1 and egress 1.1.4, because the output chain began with
  `ct state established,related accept`. The issue is now closed by pull request 2346, and the egress sources
  at commit `e564cd1` (2026-11-13) hold the matching code: `pkg/nftables/established_drop.go` defines the
  destinations whose established flows a policy change must tear down, and `pkg/nftables/conntrack_linux.go`
  works on the conntrack table. That the teardown completes before the policy request returns, as the issue
  asked, was not tested here. The same tree also holds a transparent mitmproxy mode
  (`docs/mitmproxy-transparent.md`) and revision, quarantine and persistence packages for policy updates,
  which the 2026-10-01 text does not describe.

### Kubernetes agent-sandbox

- **Bet**: a thin Kubernetes layer (`Sandbox`, `SandboxTemplate`, `SandboxClaim`, `SandboxWarmPool`). Every
  security property is delegated to the `RuntimeClass`, the CNI and admission control.
- **Strengths**: standard objects, warm pools, and a documented fix for a cross-tenant attack through
  Service-selector label spoofing.
- **Weaknesses**: its own threat model says "Agent Sandbox itself does not implement isolation". The
  template's default egress allows everything except private and metadata ranges, and DNS goes to public
  resolvers. A bare `Sandbox` gets none of that. The router's default authoriser is `AllowAll`. The core API reached `v1beta1` with v0.5.0 on 2026-06-24 and
  the quickstart now covers gVisor on KIND and Kata on minikube. The README read on 2026-11-13 repeats that the
  project delegates isolation to `RuntimeClass` runtimes and pins `v1.0.2` in its install example; sources
  still disagree on the latest release, so the analysed commit is the only firm reference. Code read on
  2026-11-13 at commit `13470fe` (2026-11-12): `extensions/controllers/utils.go` still applies a "secure by
  default" mode only when the template's `NetworkPolicyManagement` is empty or `Managed` and it has no
  `networkPolicy`; in that mode it sets `DNSPolicy` to `None` with the public resolvers `8.8.8.8` and
  `1.1.1.1`, and it turns off the service-account token mount whenever the template does not say otherwise.
  Both the core and the extensions APIs are at `v1beta1`, and the router's `AllowAll` authoriser is still the
  default (`sandbox-router/authz/authorizer.go`). The `ipBlock` exceptions that give the "everything except
  private and metadata ranges" egress were not located again in the controllers.

### llm-sandbox

- **Bet**: orchestration convenience over containers you already run. The README read on 2026-11-13 now also
  lists local backends without a daemon: Bubblewrap, NsJail, Windows MXC and WSL2 Bubblewrap, next to Docker,
  Podman and Kubernetes. The analysed commit has only the container backends, so the "containers" description
  in the landscape table and the weaknesses below apply to the container backends. Code read on 2026-11-13 at
  commit `abdddb2` (2026-11-06): `bubblewrap.py` starts `bwrap` with `--unshare-all`, `--unshare-user`,
  `--disable-userns`, `--cap-drop ALL`, `--clearenv`, `--new-session` and `--die-with-parent`, adds
  `--share-net` only when the sandbox network is `host`, mounts the project read-only and loads a seccomp
  filter; `nsjail.py` builds an optional Kafel seccomp policy and passes a time limit. These local backends are
  closed to the network by default, unlike the container backends. The container backend still starts as
  `"user": "root"` (`docker.py`), tar extraction still uses `tarfile.data_filter` (`core/mixins.py`), and
  `is_safe` is still defined (`core/session_base.py`) without a caller anywhere in the package, which matches the
  claim that `run()` does not apply the policy.
- **Strengths**: fail-closed tar extraction (`tarfile.data_filter`), written after
  GHSA-crfw-xvcm-hjxj (found on the repository, not yet in the global database). Package-name allow-lists
  per ecosystem, against shell injection.
- **Weaknesses**: root, open network and no limits by default. `runtime_configs` is passed through unfiltered,
  as its own documentation warns. `SecurityPolicy` is a regex that `run()` never calls. The archive-extraction advisory
  (GHSA-crfw-xvcm-hjxj) was fixed in 0.3.45 on 2026-09-28, and 0.3.46 followed, titled "Native Linux and experimental Windows backends"
  (releases page read on 2026-11-13; its notes say Windows build success is not evidence that the enforcement was exercised); its severity and CVE identifier were not found. The README still calls the policies advisory.

### Modal Sandboxes

- **Bet**: gVisor, or a VM, plus a small set of network settings validated by the client.
- **Strengths**: block, CIDR list or domain list, checked before the call. `block_network=True` excludes both
  lists, while the two lists can be combined additively (Modal's networking page, read on 2026-11-13). Header
  injection with `$KEY` templates, where the secret never enters the sandbox. GPU, and GPU memory snapshots
  driven by gVisor's checkpoint.
- **Weaknesses**: network open by default. The domain list only covers TLS on port 443, matched by SNI.
  gVisor is a user-space kernel:
  [CVE-2026-96812](https://osv.dev/vulnerability/CVE-2026-96812) (escape through CUSE passthrough) and
  [CVE-2025-2713](https://osv.dev/vulnerability/CVE-2025-2713) affect gVisor itself. Whether they apply to
  Modal's deployment is not known. Per Modal's SDK release notes seen in a search on 2026-11-13, gVisor is
  still the default runtime, `runtime="vm"` selects a full VM since 1.6.0 (2026-09-28), a running sandbox's
  outbound policy can be replaced (`updateNetworkPolicy`, described by a third party as alpha) and the domain
  allowlist is described as beta with a domain-fronting caveat.

### Vercel Sandbox

- **Bet**: a Firecracker microVM and the richest declarative network policy in the field.
- **Strengths**: CIDR and domain rules, matchers on method, path, query and headers, and exactly one action
  per rule: transform, forward or respond. TLS interception only on the hosts that need it, with a CA per
  sandbox. Policy replaced while the sandbox runs. Very candid documentation of its own pitfalls
  ([Firewall](https://vercel.com/docs/sandbox/concepts/firewall)).
- **Weaknesses**: `allow-all` by default. DNS open under `subnets.allow`. Domain fronting acknowledged. UDP
  and ICMP not documented. Per Vercel's changelog seen in a search on 2026-11-13, the full firewall
  (egress policies, credential brokering, request proxying, request matchers) reached the Hobby plan on
  2026-08-05 and Postgres connections pass through it; a third-party summary says the firewall runs on the
  host and filters DNS with the same domain policy, which this entry's DNS remark does not reflect and which
  was not checked in the documentation.

### Cloudflare Sandbox

- **Bet**: no policy language at all. The policy is JavaScript in the Worker, and the container sits in a
  Firecracker microVM.
- **Strengths**: as expressive as code can be: rules with state, changed without a redeploy. Credentials
  reached through fictitious host names (`*.sandbox.internal`) that exist only inside the interception.
- **Weaknesses**: nothing validates the policy, and every application rewrites its own. With internet on,
  nothing filters. The overview page, read on 2026-11-13 (last updated 2026-09-30), now presents two sandbox
  environments, and says each container instance is a microVM with its own kernel and network, with an
  `enableInternet` switch at start; only the container environment was read. A cross-tenant leak of residual disk data (dm-thin pools without block zeroing) was fixed
  in September 2026 ([Cloudflare's disclosure](https://blog.cloudflare.com/containers-cross-tenant-vulnerability/)).

### AWS AgentCore, Azure dynamic sessions, Docker Sandboxes

- **AWS AgentCore Code Interpreter**: three network modes and an IAM role, nothing finer. In "sandbox" mode,
  DNS leaked and was turned into a command channel. AWS first called it intended behaviour. The SDK had an
  argument injection, [CVE-2026-16796](https://nvd.nist.gov/vuln/detail/CVE-2026-16796). Sources disagree on whether the
  "sandbox" mode DNS channel was later closed: BeyondTrust's timeline says remediated on 2026-04-15, another
  vendor says a fix was validated on 2025-12-30, a March 2026 note and a press report say AWS only changed
  the documentation, and a lab test found VPC mode still leaking DNS. Test DNS egress before relying on it.
- **Azure dynamic sessions**: one Hyper-V VM per session, at the scale of Copilot. Egress is a single on/off
  switch per pool, closed by default. The managed identity is off by default; the documentation warns that
  turning it on lets any code in the session mint tokens. A search on 2026-11-13 reports a separate preview
  resource type, Azure Container Apps Sandboxes (June 2026), with per-sandbox egress rules according to one
  source; dynamic sessions themselves keep the per-pool egress switch.
- **Docker Sandboxes**: a microVM with its own Docker Engine. Deny by default with presets, rules per host,
  credentials injected by the proxy. The security page, read on 2026-11-13, adds that outbound TCP goes
  through the host proxy, UDP egress is experimental and follows the same policy, and ICMP is blocked. In 2026, its file-sharing bridge was the weak point:
  [CVE-2026-77179](https://nvd.nist.gov/vuln/detail/CVE-2026-77179) and
  [CVE-2026-79994](https://nvd.nist.gov/vuln/detail/CVE-2026-79994) (symlink TOCTOU escapes), and
  [CVE-2026-17106](https://osv.dev/vulnerability/GO-2026-6253), a bug in the shared `moby/go-archive` library.
  A search on 2026-11-13 adds CVE-2026-103916 (`sbx cp` does not enforce the access restrictions, fixed in
  0.51.0 on 2026-11-03), and describes CVE-2026-79994 as a flaw of the guest-to-host Unix-socket relay, where
  the entry above calls it a symlink race; CVE-2026-77179 is a flaw of the virtio-fs host server, fixed in
  0.42.0. Which description is right was not settled.

## Primary source examples

These source locations support the key distinctions in the comparison:

- [OpenShell network broker](https://github.com/NVIDIA/OpenShell/blob/021400be8af471f8669369e679de3e18cf0bd672/crates/openshell-sandbox/src/network_broker.rs#L840-L850): protocol-specific socket decisions.
- [E2B TCP firewall](https://github.com/e2b-dev/runtime/blob/23f7a0f89dc3645afc5a3026c363bdd6c6f281c1/packages/orchestrator/pkg/tcpfirewall/handlers.go#L163-L184): internal-address rejection before connect.
- [Vercel network policy types](https://github.com/vercel/sandbox/blob/6fc8e16fd606beab8f99546482f11cc40c3e5a8e/packages/vercel-sandbox/src/network-policy.ts#L81-L94): mutually exclusive rule actions.
- [Cloudflare example policy](https://github.com/cloudflare/sandbox-sdk/blob/f9e972a14123bef3b93e9bb337bab6e83419fe7e/examples/outbound-workspace/src/rules.ts#L28-L39): deny, handler, allow, then default deny.
- [RestrictedPython AST transformer](https://github.com/zopefoundation/RestrictedPython/blob/c5066f7d5b2c7538c67c2f8c4635d681c2b325aa/src/RestrictedPython/transformer.py#L500-L519): unknown AST nodes are refused.

## Where PySandboxes stands

**What only PySandboxes does.** No other solution in this survey controls what the Python code itself does.
That means imports, a registry of 152 sensitive functions, and code arriving as a string, which is parsed,
rewritten and run under a budget. It is the only solution that confines one function rather than a process,
a pod or a VM. It is one of two that write their own policy from observed behaviour; OpenShell is the other,
with an advisor rather than a recording. Unlike most solutions, which avoid the problem by never
unpickling, it returns real Python objects from the sandbox, and it unpickles them under a guard. And it lets the user choose among eight Linux boundaries, from Landlock with no extra binary, through namespaces
(`bwrap`, `unshare`, `firejail`) and a user-space kernel (`gvisor`), up to a VM with its own kernel (`smolvm`,
`qemu`, `qemu-microvm`), plus Seatbelt on macOS and AppContainer on Windows.

**What the field does better.**

- *A stronger default boundary.* Platforms give every sandbox its own kernel. PySandboxes offers a VM
  (`smolvm`, a micro-VM that starts in about a second; `qemu` and `qemu-microvm`, which take 13 to 20 s) and a
  user-space kernel (`gvisor`), but none is the default: the default is `landlock`, which shares the host
  kernel, as do `bwrap`, `unshare` and `firejail`. None restores a VM from a snapshot. A VM run without
  `/dev/kvm` is emulated and carries no isolation claim.
- *The network above layer 4.* There is no TLS interception, no method or path rules, no protocol-aware
  rules. Nine solutions match domain rules on the live connection (SNI, `Host`, proxy). PySandboxes resolves names once at start (`net-resolve=pinned`), or when the program asks, through a
  filtering resolver on the host (`net-resolve=runtime`, on most providers); it still sees no SNI and no `Host`
  header.
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
- DNS stays a low-rate exfiltration channel under every provider that owns a network namespace, and `smolvm`
  lets a program look up subdomains of an allowed host; see [Weaknesses](weaknesses.md#os-provider-limitations).
- `smolvm` filters TCP by address only, so a rule with a port opens every port of its address.
- QEMU and QEMU microvm enforce `expose-ro` with read-only 9p exports, covered by end-to-end tests; see the [provider audit](audit-native-guard-study.md#qemu-expose-ro-is-enforced-by-a-read-only-9p-export).

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
| PySandboxes | [pprados/pysandboxes](https://www.github.com/pprados/pysandboxes), `develop` at `2601d77b` (release 0.12.0, re-read 2026-11-13) |
| RestrictedPython | [`c5066f7`](https://github.com/zopefoundation/RestrictedPython/tree/c5066f7d5b2c7538c67c2f8c4635d681c2b325aa) |
| smolagents | [`c30b115`](https://github.com/huggingface/smolagents/tree/c30b115286e000e98711fae5e85993547b73d826) |
| langchain-sandbox | [`fac037c`](https://github.com/langchain-ai/langchain-sandbox/tree/fac037cb46cac3d60aa370feeb1e1f68a1ed91fa) |
| OpenShell | [`021400b`](https://github.com/NVIDIA/OpenShell/tree/021400be8af471f8669369e679de3e18cf0bd672), [docs](https://docs.nvidia.com/openshell/) |
| sandbox-runtime | [`5d196e0`](https://github.com/anthropics/sandbox-runtime/tree/5d196e0937ccdd9bedb83b27879a7a2ecd3a0dd2), [Claude Code sandboxing](https://code.claude.com/docs/en/sandboxing) |
| Codex | [`444da31`](https://github.com/openai/codex/tree/444da310e108da16aaeb18fd790b0ac464f08aca) |
| microsandbox | [`b3843eb`](https://github.com/superradcompany/microsandbox/tree/b3843eb12344c928662323378b9dee113b12f397) (v0.7.5); a search on 2026-11-13 shows [PR 2040](https://github.com/superradcompany/microsandbox/pull/2040) bumping it to 0.7.15, not re-read |
| E2B | SDK [`f713914`](https://github.com/e2b-dev/E2B/tree/f7139140d34ad440e35f4ec7d1bdd183f1b35a6e), runtime [`23f7a0f`](https://github.com/e2b-dev/runtime/tree/23f7a0f89dc3645afc5a3026c363bdd6c6f281c1), [docs](https://e2b.dev/docs) |
| Daytona | v0.190.0 [`01c502b`](https://github.com/daytonaio/daytona/tree/01c502bb1f1ff8f2885d0cd490e043736083dca8) |
| OpenSandbox | [`c7dc78a`](https://github.com/opensandbox-group/OpenSandbox/tree/c7dc78a4090e5de2b9119e9bd93952cae24f87bd) |
| Kubernetes agent-sandbox | [`82d410e`](https://github.com/kubernetes-sigs/agent-sandbox/tree/82d410efd5a279e887cdcf8c01e742a345fef63d) |
| llm-sandbox | [`7361f5e`](https://github.com/vndee/llm-sandbox/tree/7361f5e5ca06b5597f977f13efbe859f481cb01e) |
| Modal | client [`83cd277`](https://github.com/modal-labs/modal-client/tree/83cd27748d1fc0ac6adbf5acc8e9a3bfbf85208e), [networking](https://modal.com/docs/guide/sandbox-networking), [security](https://modal.com/docs/guide/security) |
| Vercel | client [`6fc8e16`](https://github.com/vercel/sandbox/tree/6fc8e16fd606beab8f99546482f11cc40c3e5a8e), [firewall](https://vercel.com/docs/sandbox/concepts/firewall) |
| Cloudflare | client [`f9e972a`](https://github.com/cloudflare/sandbox-sdk/tree/f9e972a14123bef3b93e9bb337bab6e83419fe7e) (1.0 preview; a search on 2026-11-13 shows 1.0.0 released and 1.0.3 on 2026-10-22, and says a container has no Internet unless `enableInternet: true` is passed, whereas the table above gives it as open: not re-read, so that cell may be out of date), [Containers outbound traffic](https://developers.cloudflare.com/containers/platform-details/outbound-traffic) |
| AWS AgentCore | [AgentCore documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-tool.html), [BeyondTrust](https://www.beyondtrust.com/blog/entry/pwning-aws-agentcore-code-interpreter), [Unit 42](https://unit42.paloaltonetworks.com/bypass-of-aws-sandbox-network-isolation-mode/) |
| Azure dynamic sessions | [Container Apps sessions](https://learn.microsoft.com/en-us/azure/container-apps/sessions) |
| Docker Sandboxes | [Docker Sandboxes documentation](https://docs.docker.com/ai/sandboxes/security/) |

CVE numbers were checked on 2026-10-01 against NVD, OSV and the GitHub Advisory Database. The ones added on
2026-11-13 come from search results and were not looked up in those registries.

On 2026-11-13, all eighteen other entries were re-checked in three passes. First, one web search each, whose
result summaries were read; what a search returned is quoted as such in the entry, with its date. Second, a
primary page of each (README, documentation page or releases page) was fetched and compared with the text,
and the entries were corrected where it disagreed. Third, for the twelve open-source projects below, a
shallow clone of the default branch was searched by keyword, which is not a code analysis. Commits seen
(all read on 2026-11-13): sandbox-runtime `0bbebed0`, OpenShell `7cfa0c09`, RestrictedPython `9d7aeb26`,
microsandbox `28bdced5`, smolagents `96f33fa` (2026-10-06), llm-sandbox `abdddb2`, OpenSandbox `e564cd1`,
Codex `69231e1`, E2B infra `ee78f06`, agent-sandbox `13470fe`, Daytona `ec4c21b` (2026-06-25, frozen) and
langchain-sandbox `fac037c` (2026-01-14, archived). What the keyword searches found: smolagents still defines
`MAX_OPERATIONS` (10,000,000) and `MAX_WHILE_ITERATIONS` (1,000,000); llm-sandbox ships `bubblewrap.py`,
`nsjail.py` and `wsl2_bubblewrap.py` next to its container backends; agent-sandbox still has `AllowAll` as the
router's default authoriser; Codex's `linux-sandbox` crate still holds `seccomp.rs`, `bwrap.rs` and
`launcher.rs`; OpenSandbox's server configuration and examples still reference gVisor, Kata and Firecracker.
The Daytona search for `domainAllowList` found nothing under `apps`, which proves nothing about the runner
claim. The analysed commits of the table above, the claims drawn from the source code and the 45-feature
matrix keep their 2026-10-01 state, and no matrix cell was changed even where a source suggests it may be out
of date (Cloudflare's default egress, Vercel's DNS). Redoing them means reading the code of each project.
