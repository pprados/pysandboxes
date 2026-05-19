# Firejail security audit
_Exported on 24/03/2026 at 11:10:37 UTC+1 from Cursor (2.6.20)_

---

**User**

/pysandboxes-os-provider-security-audit firejail

---

**Cursor**

Auditing the Firejail OS provider per the attached skill: tracing implementation, env/fs/network handling, and handoff risks.

Verifying child environment construction when socket rules are absent vs present:

Here is the **OS provider security audit for Firejail** (`pysandboxes` + `py-sandbox=false`), aligned with the skill template and repo paths.

---

## A. Environment variables

**Verdict:** partial  
**Context:** standalone host + provider `firejail` (container/K8s effectively **N/A** for supported images per [wiki/firejail.md](wiki/firejail.md))

**Findings:**

- The **outer** process passed to `asyncio.create_subprocess_exec` always gets `env = {**os.environ, **extra_envs}` after a branch that is overwritten, so the **Firejail parent** always receives the **full host environment** regardless of `learn` or `all_rules.envs` ([`client_subprocess_sse_daemon.py`](pysandboxes/remote/client_subprocess_sse_daemon.py) lines 535–540).
- When **`socket_rules` is non-empty**, `_firejail_args` appends `/usr/bin/env -i` and only `all_rules.envs` entries before `python -m … main_sandbox` ([`firejail_sse_daemon.py`](pysandboxes/remote/firejail_sse_daemon.py) 597–601), so the **inner Python** can be reduced to profile env for that configuration.
- When **`socket_rules` is empty**, that `/usr/bin/env -i` block is **not** used; the interpreter inherits environment through Firejail from the parent, which is **much closer to the host** (template only clears `PYTHONSTARTUP` via `--env=PYTHONSTARTUP=` in [`firejail.template`](pysandboxes/templates/firejail.template)).
- With `use_py_sandbox=False`, **`guard_envs` is not activated** ([`py_sandbox.py`](pysandboxes/py_sandbox.py) 354–376); env policy is **not** enforced in Python.
- **`pin_dns`:** [`main_sandbox.py`](pysandboxes/remote/main_sandbox.py) still calls `apply_pin_dns_resolution(socket)` when `pin_dns` is set (378–384), so Python-level name resolution can follow pins even without the full sandbox.

**Weaknesses:**

- Full host env on the **Firejail-invoking** process (secrets, `KUBERNETES_*`, `AWS_*`, tokens) unless the outer launcher itself is already stripped.
- **No-socket-rules** profiles: inner env is **not** minimized to `all_rules.envs`.
- **`apply_pin_dns_resolution`** only patches the **`socket` module**; libc / C extensions / subprocesses can still resolve outside pins ([`propagation-and-toctou.md`](.cursor/skills/pysandboxes-os-provider-security-audit/references/propagation-and-toctou.md)).

**Recommendations:**

- Treat **socket/network rules** as the configuration that triggers **clean inner env**; if you need strict env without network rules, extend the launcher to always use `/usr/bin/env -i` + allowlist (or document that firejail-only mode requires socket rules for env hygiene).
- Run `python-sb` from a **minimal parent env** (wrapper that clears sensitive variables before start).
- For `pin_dns`, assume **partial** DNS pinning unless egress/DNS is enforced with **netfilter + fixed resolvers** inside the jail.

**Cannot strengthen (reason):**

- Firejail does not magically strip the **parent** process env; only the **inner** command line can be made minimal, and only if the code path adds `env -i`.

---

## B. Filesystem read/write

**Verdict:** partial  
**Context:** standalone + `firejail`

**Findings:**

- Firejail arguments are built from [`firejail.template`](pysandboxes/templates/firejail.template) (includes `disable-*.inc`, `private-etc`, `noroot`, `nonewprivs`, caps drop, etc.) plus **dynamic** `--whitelist` / `--read-only` / `--read-write` / `--blacklist` from `AllRules` ([`firejail_sse_daemon.py`](pysandboxes/remote/firejail_sse_daemon.py) 392–462).
- Whitelist includes **`sys.executable`** (with symlink follow), **`sys.path`** dirs, **site-packages**, **`IgnoreRule` → `--blacklist`**, **`ExposeRule` → whitelist + RO/RW**, and the **temp area** for netfilter FIFOs / config pipe parent dir (418–422, 479–483).
- **`/etc` is skipped** for some whitelist/read-only operations (`_firejail_skip_path`) to satisfy Firejail quirks (432–435, 445–462).

**Weaknesses:**

- With **`use_py_sandbox=False`**, **no** `guard_files` monkey-patching; **only** Firejail’s view of the profile applies. Mis-generated or too-broad **expose-rw** rules directly become **writable** mounts (`--read-write`).
- Executable resolution uses `follow_links_executable` with a **FIXME** (397); symlink/edge cases around the interpreter path can affect what gets whitelisted.
- Template **`--private-*` full lockdown** is mostly commented out; isolation is **whitelist-centric**, not “empty FS + explicit grants,” so policy quality depends on rules + template.

**Recommendations:**

- Keep **expose rules** minimal; avoid broad RW mappings toward host trees.
- Prefer **read-only** defaults; justify every `--read-write`.
- Review Firejail **profile includes** on the target distro (they evolve with the `firejail` package).

**Cannot strengthen (reason):**

- Firejail is not a VM; **kernel / LSM / another outer container** still define the ceiling; 9p-style copy-in is N/A here.

---

## C. Sensitive files (`.env`, keys, configs)

**Verdict:** partial  
**Context:** standalone + `firejail`

**Findings:**

- Template uses **`--private-etc=hosts,resolv.conf,nsswitch.conf`** and aggressive **disable-* includes**, which reduces exposure of full `/etc`.
- Paths not **whitelisted** are generally inaccessible **inside** the jail subject to Firejail’s mount model; **whitelisted** paths (e.g. project dir via expose mapping) remain readable/writable per rule.

**Weaknesses:**

- **`.env` / credentials** under a **whitelisted project tree** are **readable** by untrusted code—same as any exposed path into the jail.
- **No Python file guard** when `py-sandbox=false`; there is no second layer to block `open()` to an allowed-but-sensitive file.
- **Host `HOME`** is not inherently protected if a rule or template behavior exposes it (avoid wide expose mappings).

**Recommendations:**

- Never whitelist **`~/.ssh`**, cloud credential dirs, or kubeconfig unless strictly required; use **narrow** read-only expose paths.
- Keep secrets **outside** whitelisted trees or use an outer **container** with read-only root and no secret mounts.

**Cannot strengthen (reason):**

- If the profile **allows** a path, Firejail **intentionally** allows it; policy must be correct at configuration time.

---

## D. Network and DNS

**Verdict:** partial (policy-dependent)  
**Context:** standalone + `firejail`

**Findings:**

- With **socket rules**, code adds **`--net=<bridge>`** (unless `os_sandbox_params` already set `net`), **`--dns=`** from upstream IPv4 DNS ([`get_upstream_dns`](pysandboxes/remote/firejail_sse_daemon.py) 511–547), and **`--netfilter` / `--netfilter6`** from FIFO-fed iptables-format rules (549–586).
- **`/etc/firejail/firejail.config`**: default **`restricted-network`** behavior can **force exit** if socket rules exist without `restricted-network no`; explicit **`restricted-network yes`** causes **socket rules to be skipped** at the Firejail layer with only a warning (485–505)—**large policy downgrade**.
- **IPv6 / pin_dns → Firejail `--dns`**: IPv6 DNS path is effectively **TODO** (commented 523–528).
- **`pin_dns`:** still applied in **`main_sandbox`** via **`socket` patches** (see A); **not** a substitute for kernel packet filter for non-Python resolvers.

**Weaknesses:**

- Misconfigured **`firejail.config`** can **remove** netfilter-based enforcement while the profile still suggests isolation.
- **Bridge mode** implies a **different threat model** (routing to host/LAN); must align with [`wiki/firejail.md`](wiki/firejail.md) bridge guidance.
- **Cloud metadata** (e.g. `169.254.169.254`) depends entirely on **socket/netfilter rules**; not automatic.

**Recommendations:**

- Enforce **`restricted-network no`** where net rules are required; treat **`restricted-network yes`** as **incompatible** with socket-rule security goals.
- Encode **explicit egress allowlists** in netfilter rules; do not rely only on Python `pin_dns`.
- For metadata exposure, add **explicit DROP** rules in profile/socket rules.

**Cannot strengthen (reason):**

- **DoH / non-53 DNS** or raw sockets may bypass naive DNS-only assumptions; full egress control needs **comprehensive** filtering, not DNS alone.

---

## E. TOCTOU / propagation races

**Verdict:** partial  
**Context:** standalone + `firejail`

**Findings:**

- **Daemon config:** host uses a **FIFO under `tempfile.TemporaryDirectory()`** with a random name, writes **pickle** once, then unlinks ([`launch_sandbox`](pysandboxes/remote/client_subprocess_sse_daemon.py) 163–222, [`main_sandbox`](pysandboxes/remote/main_sandbox.py) 289–294). Same-UID `/tmp` scraping risk is **low** vs predictable global paths.
- **Netfilter FIFOs:** `os.mkfifo` under the same temp dir; a **background thread** writes rules then unlinks (561–585). Firejail consumes the FIFO as documented for `--netfilter`.

**Weaknesses:**

- **Expose rule sources** on the host could be **swapped** (symlinks) between rule build and Firejail mount if paths are attacker-controlled—mitigation is **resolve and validate** paths at launch (see references).
- **Interpreter / sys.path follow_links** (FIXME) is a **TOCTOU-class** concern for **what** gets whitelisted.
- **`pickle.loads` on trusted parent data** is acceptable only if the **parent is trusted**; a compromised host still owns the child config (inherent).

**Recommendations:**

- Use **stable, administrator-controlled** expose sources; resolve symlinks where appropriate before passing to Firejail.
- Prefer **single-use temp dirs** with tight permissions (already using `TemporaryDirectory`).

**Cannot strengthen (reason):**

- Cannot remove **host compromise** from the threat model; child always trusts the launching host.

---

## F. Provider-specific limits (Firejail)

**Verdict:** N/A (meta) / partial  
**Context:** standalone + `firejail`; **container/K8s** documented as unsupported for this provider

**Findings:**

- **`REPLACE = False`** in [`firejail_sse_daemon.py`](pysandboxes/remote/firejail_sse_daemon.py) (56–58): **`update_rules_and_activate`** does **not** delegate file/socket rules to Firejail by shrinking Python-side rules (intended future behavior). With **`py-sandbox=false`**, that matters less because Python guards are off anyway; **OS translation** is what remains.
- Firejail often involves **setuid** / privileged helpers—historical **CVE class** “sandbox escape” applies to **Firejail itself**, not only pysandboxes.
- **Docker/Podman/K8s:** project states Firejail is **not** the right layer there ([`wiki/firejail.md`](wiki/firejail.md)); use **bwrap/unshare/qemu** instead ([`deployment-scenarios.md`](.cursor/skills/pysandboxes-os-provider-security-audit/references/deployment-scenarios.md)).

**Weaknesses:**

- **Nested sandboxes** (Firejail inside an unprivileged container) are **fragile** or **unavailable**; **rootless** / locked-down hosts may block features.
- **Defense depth** is **one OS tool** + profile; unlike QEMU, no hardware VM boundary.

**Recommendations:**

- Track **Firejail security advisories** and distro packaging (setuid vs user namespaces).
- For **CI/containers**, select **bwrap/unshare/qemu** per project docs.

**Cannot strengthen (reason):**

- **VM-grade** isolation or **Kubernetes-native** policy is **out of scope** for the Firejail provider in this repo.

---

## Executive summary

- With **`py-sandbox=false`**, **file/env/socket guards do not run** in Python; **Firejail’s generated profile + optional netfilter** carry the boundary. **`pin_dns`** still applies via **`socket` monkey-patches** in `main_sandbox`, which is **partial** for DNS.
- **Inner env is strict (`/usr/bin/env -i` + profile)** mainly when **`socket_rules` is non-empty**; **without socket rules**, the inner process keeps a **much larger** inherited environment.
- The **Firejail parent process** always receives **full `os.environ`** from the launcher, which is **relevant for secret exposure** on the host side of the fork/exec chain.
- **Network safety** depends on **`/etc/firejail/firejail.config`** and actually applied **`--netfilter`** rules; **`restricted-network yes`** can **silently drop** Firejail-side network filtering.
- **Deployment:** Firejail is aimed at **standalone Linux**; **Docker/Podman/K8s** should use **other providers** per project documentation.

## Residual risk

Even with tight profiles and netfilter: **host compromise**, **Firejail implementation bugs**, **over-broad expose/whitelist rules**, **non-Python DNS/resolver paths**, and **metadata/exfiltration unless explicitly blocked** remain. **Outer** hardening (dedicated user, minimal parent env, optional LSM/AppArmor, network segmentation) is still necessary for hostile workloads.

---

**Evidence map (primary):** [`pysandboxes/remote/firejail_sse_daemon.py`](pysandboxes/remote/firejail_sse_daemon.py), [`pysandboxes/remote/client_subprocess_sse_daemon.py`](pysandboxes/remote/client_subprocess_sse_daemon.py), [`pysandboxes/remote/main_sandbox.py`](pysandboxes/remote/main_sandbox.py), [`pysandboxes/py_sandbox.py`](pysandboxes/py_sandbox.py), [`pysandboxes/templates/firejail.template`](pysandboxes/templates/firejail.template), [`wiki/firejail.md`](wiki/firejail.md).
