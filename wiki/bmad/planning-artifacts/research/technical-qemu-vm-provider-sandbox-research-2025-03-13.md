---
stepsCompleted: [1, 2, 3, 4, 5, 6]
inputDocuments: []
workflowType: 'research'
lastStep: 6
research_type: 'technical'
research_topic: 'QEMU/VM provider for Python isolation with emulator (KVM optional), iptables rules inside VM, unprivileged container execution'
research_goals: 'Study solutions to add a pysandboxes provider based on QEMU (or qemu-server) that isolates Python code in a VM; support KVM or TCG to run in unprivileged containers; apply iptables rules inside the VM to avoid requiring network privileges (NET_ADMIN) in Docker/Podman.'
user_name: 'philippe'
date: '2025-03-13'
web_research_enabled: true
source_verification: true
---

# Research Report: technical

**Date:** 2025-03-13  
**Author:** philippe  
**Research Type:** technical  

---

## Research Overview

This technical research covers adding a **VM-based isolation provider** to the pysandboxes framework: an **abstract class `VMSSEDaemon`** (inheriting from `BaseSubProcessDaemon`) of which **`QemuSSEDaemon`** is the first implementation. Constraints: (1) execution possible **without privileges** (container without `/dev/kvm` or NET_ADMIN), so **QEMU in TCG** when needed; (2) **network** controlled by **iptables rules inside the VM**; (3) **injection of parameters and rules via named pipe** (like unshare/firejail), with the option of rules embedded in the guest script; (4) **VM images** in a **standard directory** (e.g. `$XDG_DATA_HOME/pysandboxes/vm-images`, configurable and shareable); (5) **clean shutdown** via **QEMU Guest Agent**. The document summarises the options and describes the architecture (VMSSEDaemon / QemuSSEDaemon, lifecycle, QGA, image directory).

---

## 1. Context and objectives

### 1.1 pysandboxes framework

- Current providers (subprocess, bwrap, firejail, unshare, landlock) rely on OS mechanisms (namespaces, Landlock, slirp4netns, etc.).
- Each daemon extends `BaseDaemon` (or `BaseSSESandbox` / `BaseSubProcessDaemon`), implements `_start`, `_stop`, `_shutdown`, and exposes `call_in_sandbox` / `async_call_in_sandbox`.
- Communication with the sandbox is via **SSE over HTTP** (the daemon in the sandbox listens on a port; the client connects to `localhost:port`).
- Network rules (guard_socket) are translated into **iptables rules** (module `netfilter`, `rule_to_netfilter`) and applied either in the namespace (unshare) or via firejail, etc.

### 1.2 VM provider objectives

- **Stronger isolation**: run Python code inside a VM (Linux guest) for a stronger security boundary than namespaces alone.
- **Unprivileged container**: no `--privileged`, no `NET_ADMIN`, no mandatory access to `/dev/kvm` → QEMU must be able to run in **TCG** (software) and network must not rely on TAP/bridge interfaces on the host.
- **Iptables inside the VM**: network policy (allow/deny by port, protocol, direction) is applied **in the guest** via iptables, so the host or container network does not need to be modified.

---

## 2. QEMU vs “qemu-server”: clarification

- **QEMU**: emulator/virtualiser (system mode) that runs a full VM (kernel + userspace). It is the core building block.
- **qemu-server** (Proxmox): set of **Proxmox VE** scripts and APIs (Perl, REST API) to create, configure, and manage QEMU VMs on a Proxmox node. It is not a standalone “QEMU server” binary.

For a provider **integrated into pysandboxes** and usable in any container (not necessarily Proxmox), the relevant target is **QEMU from the command line** (or via a lib such as python-qemu), not the Proxmox API. One can take inspiration from qemu-server options and practices (network, disks, devices) without depending on Proxmox.

**Reference:** [Proxmox qemu-server](https://github.com/proxmox/qemu-server), [QEMU system emulation](https://www.qemu.org/docs/master/system/index.html).

---

## 3. Unprivileged execution: KVM vs TCG

### 3.1 KVM

- Requires `/dev/kvm` and usually privileges (e.g. `kvm` group or root).
- In a container: you need to pass `--device /dev/kvm` and often capabilities (CAP_SYS_ADMIN or privileged execution) depending on the runtime.
- **Not suitable** when the goal is “unprivileged container”.

### 3.2 TCG (Tiny Code Generator)

- QEMU can run **without KVM**, in pure software emulation (TCG).
- No access to `/dev/kvm`, no special privileges.
- **Drawback**: performance is much lower than KVM (roughly 5–20× slower depending on workload). For short-lived Python sandbox execution, this is often acceptable.

**Conclusion**: for “unprivileged container”, the provider must **detect** the presence of `/dev/kvm` (and permissions) and, when absent, launch QEMU with **`-enable-kvm` disabled** (TCG). Same binary, same image, VM execution possible everywhere.

**References:** [QEMU user mode](https://qemu.org/docs/master/user/main.html), [TCG without KVM](https://stackoverflow.com/questions/34320595/how-to-run-qemu-without-tcg-and-without-kvm), [QEMU in Docker / TCG](https://github.com/wtdcode/DebianOnQEMU).

---

## 4. Network: no host privileges, iptables in the VM

### 4.1 QEMU “user” network (`-net user`)

- **`-net user`** (user-mode stack): QEMU does NAT/slirp in userspace. No TAP interface, no bridge, **no root privilege** on the host.
- The guest typically sees IP 10.0.2.15, gateway 10.0.2.2; outbound connections are translated into connections from the QEMU process on the host.
- By default, **inbound** connections to the guest are blocked except explicit port forwarding (`hostfwd=tcp:...-:...`).

This is the best fit for an unprivileged container: no NET_ADMIN, no TAP.

**Reference:** [QEMU network emulation](https://www.qemu.org/docs/master/system/devices/net.html).

### 4.2 Iptables rules in the VM

- The idea is **not** to configure iptables on the host/container, but **inside the guest**.
- When the VM starts, once the (user) network is up, a script or service in the guest applies iptables rules (INPUT/OUTPUT) that match the sandbox “socket” rules (equivalent of `rule_to_netfilter`).
- Benefits:
  - No `NET_ADMIN` (or `NET_RAW`, etc.) on the container/host.
  - Network policy entirely contained in the VM.
  - Same conceptual model as unshare (netfilter in the namespace) but in the guest.

**Guest-side implementation**: image or initramfs with `iptables` (or nftables) and a script that receives the rules (mounted file, virtio-serial channel, or cloud-init config) and runs `iptables-restore` (or equivalent). Rules can be generated by the same `netfilter.rule_to_netfilter` module as for unshare, then injected into the image/guest config.

**References:** [QEMU user networking](https://www.qemu.org/docs/master/system/devices/net.html), [iptables in VM](https://unix.stackexchange.com/questions/732637/easy-secure-qemu-network-with-iptables-and-without-a-bridge-or-tap), [restricting QEMU guest](https://serverfault.com/questions/807895/restricting-guest-connections-in-qemu-virtual-machine-how).

### 4.3 Alternative: user-based filtering on the host

- If host-side network (e.g. TAP) were used, traffic could be filtered by `--uid-owner` (user running QEMU). In an unprivileged container, iptables is usually not available on the host, so this option is secondary. The “iptables inside the VM” approach remains the most consistent with the “no network privilege in Docker/Podman” constraint.

---

## 5. Host–guest communication (SSE / RPC)

The pysandboxes model assumes an **SSE server** runs in the sandbox and listens on a port (e.g. `localhost:PORT`). The (host) client connects to that port.

### 5.1 With `-net user` + port forwarding

- QEMU can open a port on the host and forward it to the guest:  
  `hostfwd=tcp:HOST_PORT-:GUEST_PORT`
- The host client connects to `localhost:HOST_PORT`; QEMU forwards to guest `GUEST_PORT`.
- No TAP, no privileges. The SSE server in the VM listens on `0.0.0.0:GUEST_PORT` (or localhost as needed).

This is the simplest way to keep the same “host HTTP/SSE client → server in sandbox” pattern.

### 5.2 Alternatives and role of QEMU Guest Agent

- **Virtio-serial / channel**: character-device communication (Unix socket on host, device in guest). Would require adapting the pysandboxes transport (protocol over the channel instead of HTTP/SSE). More complex, but avoids exposing a TCP port.
- **QEMU Guest Agent (QGA)**: the protocol is not designed for application-level RPC like SSE; it is however **recommended for clean VM shutdown**. Via QMP, the `guest-shutdown` command cleanly powers off the guest (disk sync, service shutdown) instead of killing the QEMU process. The provider should set up a virtio-serial channel for QGA and use a guest image with the `qemu-guest-agent` service installed and running.

For the first version of the provider: **hostfwd + SSE server** for RPC; **QGA for clean shutdown**.

**References:** [QEMU Guest Agent](https://qemu.org/docs/master/interop/qemu-ga-ref.html), [Virtio-serial](https://linux-kvm.org/page/Virtio-serial_API), [QMP](https://www.qemu.org/docs/master/interop/qmp-spec.html).

---

## 6. Proposed architecture for the “qemu” or “vm” provider

### 6.1 Class hierarchy (abstract VM, QEMU implementation)

- **`VMSSEDaemon`**: **abstract** class inheriting from **`BaseSubProcessDaemon`**. It encapsulates the behaviour common to all VM-based providers (lifecycle, waiting for SSE port, config injection). Concrete implementations (QEMU and others to come) inherit from it.
- **`QemuSSEDaemon`**: concrete implementation inheriting from **`VMSSEDaemon`**. The “subprocess” is the **QEMU** binary that starts the VM; inside the VM, a Python process runs the same pattern as other providers (e.g. `main_sandbox`) and starts the SSE server.
- Future implementations (e.g. another hypervisor) will also inherit from `VMSSEDaemon`.

The host daemon (QemuSSEDaemon): builds the QEMU command line (disk, kernel, initrd or image, `-net user,hostfwd=...`), starts QEMU as a subprocess, and once the VM is ready (polling the forwarded port), the SSE client connects as with other providers.

### 6.2 Parameter and rule injection (named pipe, security)

As with other implementations (unshare, firejail, subprocess), **configuration parameters** and **iptables rules** must be injected securely, **without exposing them on the command line** (avoid injection and visibility in `ps`).

- **Named pipe (FIFO)**: create a **named pipe** on the host and pass its path to the process in the VM (e.g. argument `--_config-pipe <path>` or mounting the pipe into the VM). The guest process reads the config (daemon parameters, rules, etc.) from this pipe at startup.
- **Injected content**: daemon parameters (token, port, rules, env) — same idea as `DaemonParameters` / serialised config (JSON or equivalent); **iptables rules**: list produced by **`rule_to_netfilter`**, sent in the same stream or a second channel (e.g. section of the message or second pipe). The script in the guest runs `iptables-restore` before starting the SSE server.
- **“Rules in script” option**: rules can **optionally** be embedded in the guest init script (generated at image build or instantiation). Pipe injection remains the recommended mode for flexibility and consistency with other providers.

### 6.3 Lifecycle and clean shutdown (QEMU Guest Agent)

- **`_start`**: create the named pipe(s), generate the config (params + rules) and make it available to the guest (write to the pipe after the guest opens it for reading); launch QEMU with `-enable-kvm` only if `/dev/kvm` is usable; wait for the forwarded port to respond (health check).
- **`_stop` / `_shutdown`** — **clean shutdown**: stop accepting new calls. **Priority**: use the **QEMU Guest Agent (QGA)** when available. Via QMP, send `guest-shutdown` so the system in the VM shuts down cleanly (disk sync, service shutdown), avoiding a brutal kill (SIGKILL on QEMU). If QGA is not available or times out: shutdown request to the SSE server in the VM, then SIGTERM on QEMU, then SIGKILL as last resort. Provide a **virtio-serial channel** for QGA in the QEMU command line and ensure the guest image has the `qemu-guest-agent` service installed and running.

### 6.4 Network rules and iptables in the VM

- **Socket** rules are converted to an iptables list via **`rule_to_netfilter`**. This list is **injected via the named pipe** (6.2): the script in the guest receives it at startup and runs `iptables-restore` before starting the SSE server. **Option**: rules embedded in the guest init script if they are not passed dynamically via the pipe.

### 6.5 QEMU/VM image management — standard directory

- Images (disks, kernels, initrd) must be **downloaded and stored in a standard directory**, preferably **shareable** with other technologies.
- **Proposal**: **default directory** `$XDG_DATA_HOME/pysandboxes/vm-images` (e.g. `~/.local/share/pysandboxes/vm-images`); **configurable** (environment variable or config, e.g. `PYSANDBOXES_VM_IMAGES_DIR`) to point to a shared directory (e.g. `/var/lib/vm-images`, `$XDG_DATA_HOME/vm-images`). Download on first use or via a dedicated command, with integrity verification (checksum).

### 6.6 Config / guard_provider integration

- New providers: e.g. `os_sandbox=vm` (select implementation via config) or `os_sandbox=qemu` for QEMU.
- Possible parameters: path or identifier for image (kernel, initrd, disk), defaulting to the standard directory (6.5); use KVM when available (boolean, default true); memory, CPU count. The `net=...` rules are turned into iptables and injected into the guest via the named pipe (or embedded in the script).

---

## 7. Technical stack and dependencies

### 7.1 Host (container or machine)

- **QEMU** (system mode) installed, with support for the target architectures used (e.g. x86_64 or aarch64).
- No dependency on Proxmox or qemu-server; only the `qemu-system-*` binary.
- Python 3.10+ and current pysandboxes dependencies (aiohttp, SSE, etc.).

### 7.2 Guest image

- Minimal Linux image (Debian, Alpine, or custom) with:
  - Python + pysandboxes environment (or a binary/script that starts the SSE server).
  - `iptables` (or nftables) and a script that applies rules at boot (rules read from the named pipe, or optionally embedded in the script).
  - **QEMU Guest Agent** installed and running for **clean shutdown** (recommended).

### 7.3 Performance

- TCG: latency and CPU throughput are much lower than KVM. For short Python runs (tests, jobs, user-code sandboxing), often acceptable.
- KVM: prefer when available (environment with `/dev/kvm`), without changing provider code.

---

## 8. Summary and recommendations

### 8.1 Recommended choices

| Aspect | Recommendation |
|--------|----------------|
| **QEMU vs qemu-server** | Use **QEMU** from CLI (or lib); take inspiration from Proxmox options if needed, without depending on the Proxmox API. |
| **KVM vs TCG** | **Automatic detection**: if `/dev/kvm` is available → `-enable-kvm`; otherwise TCG for unprivileged container. |
| **Network** | **`-net user`** + **hostfwd** for the SSE port; **no** TAP/bridge on the host. |
| **Iptables** | Apply rules **inside the VM** (script at boot, rules from `rule_to_netfilter`), so the container does not need NET_ADMIN. |
| **Transport** | Keep **SSE over HTTP** with **hostfwd** to minimise changes compared to other providers. |
| **Shutdown** | **QEMU Guest Agent** for clean shutdown (virtio-serial channel + `guest-shutdown` via QMP). |
| **Config / rules** | Injection via **named pipe** (like unshare/firejail), iptables rules in the stream or second pipe; option: rules embedded in guest script. |
| **Images** | Standard directory **$XDG_DATA_HOME/pysandboxes/vm-images** (configurable, shareable). |

### 8.2 Suggested implementation steps

1. **Abstract class**: introduce **`VMSSEDaemon`** (abstract) inheriting from `BaseSubProcessDaemon`; **`QemuSSEDaemon`** inherits from `VMSSEDaemon`.
2. **Specification**: document the interface (params, named pipe for config and rules, image directory, JSON/config format).
3. **Guest image**: minimal image with Python, SSE server, iptables, script that reads config and rules from the named pipe (or rules in script), and **qemu-guest-agent** for clean shutdown.
4. **Daemon**: implement `QemuSSEDaemon` with named-pipe injection, `subprocess_cmd()` returning the QEMU command line (hostfwd, QGA channel), and use of the standard image directory.
5. **Rules**: reuse `rule_to_netfilter`; inject rules via the same named pipe (or second pipe) as the config.
6. **Tests**: integration with/without KVM, with iptables rules, unprivileged container; shutdown via QGA.

### 8.3 Risks and limitations

- **TCG performance**: higher CPU load and longer run times; should be documented for users.
- **Operational complexity**: managing a guest image and its updates (security, Python).
- **Startup**: VM boot delay (longer than a simple fork/unshare) may require adapted timeouts and retries in `_start`.

---

## 9. References and sources

- [QEMU System Emulation](https://www.qemu.org/docs/master/system/index.html)  
- [QEMU Network Emulation (user, hostfwd)](https://www.qemu.org/docs/master/system/devices/net.html)  
- [Proxmox qemu-server](https://github.com/proxmox/qemu-server)  
- [QEMU User Mode (TCG clarification)](https://qemu.org/docs/master/user/main.html)  
- [Running QEMU without KVM (TCG)](https://stackoverflow.com/questions/34320595/how-to-run-qemu-without-tcg-and-without-kvm)  
- [QEMU user networking, iptables without bridge/tap](https://unix.stackexchange.com/questions/732637/easy-secure-qemu-network-with-iptables-and-without-a-bridge-or-tap)  
- [Restricting QEMU guest connections](https://serverfault.com/questions/807895/restricting-guest-connections-in-qemu-virtual-machine-how)  
- [QEMU Guest Agent](https://qemu.org/docs/master/interop/qemu-ga-ref.html)  
- [Virtio-serial API](https://linux-kvm.org/page/Virtio-serial_API)  
- [DebianOnQEMU (TCG in Docker)](https://github.com/wtdcode/DebianOnQEMU)  
- [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html) (standard directory for data / VM images).  
- pysandboxes codebase: `_os_sandbox.py`, `base_daemon.py`, `remote/sse_unshare_daemon.py`, `remote/unshare_setup.py`, `remote/sse_client_subprocess_daemon.py` (named pipe), `netfilter.py`, `guard_socket.py`.

---

**Document produced as part of BMAD technical research.**  
**Date:** 2025-03-13.  
**Objective:** Study solutions for a pysandboxes provider based on a QEMU VM, with execution possible without privileges (TCG) and iptables rules inside the VM to avoid network privileges in containers.
