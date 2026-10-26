# AppContainer (Windows)

> **Implementation status:** implemented on this feature branch and not yet released. The local Windows VM suites
> pass as both administrator and standard user. Release support remains gated on the Windows CI job passing.

The `appcontainer` provider combines a Windows AppContainer token with a Job Object. It provides an OS boundary
for native code on Windows, where `subprocess` only separates processes and the Python guards can be bypassed by
compiled code. It does not use the Hyper-V Windows Sandbox feature.

## How it works

An unconfined trampoline creates a per-run AppContainer profile and starts the actual sandbox process suspended
with that profile's package SID and the capabilities required by the profile. It assigns the child to a
`KILL_ON_JOB_CLOSE` Job Object, then resumes it. If setup fails, the child is never started unconfined. If the
trampoline exits unexpectedly, closing the Job Object kills the child.

The child runs `sys.executable -m pysandboxes.remote.main_sandbox`, like the other subprocess providers. The
trampoline grants the package SID access only to paths needed for the run, starts the SSE listener outside the
AppContainer, and hands its socket to the suspended child. A Job Object UI restriction set limits the window
station access needed by Python on service sessions such as SSH and CI runners.

## Rule enforcement

| Rule | OS enforcement | Limit |
|---|---|---|
| `expose-ro=path` | Read and execute ACL for the per-run package SID | The grant is removed at run exit. |
| `expose-rw=path` | Modify ACL for the per-run package SID | The grant is removed at run exit. |
| `ignore=pattern` | Existing matched paths are masked by stopping ACL inheritance and removing package grants | Names can remain listable; files created later under a writable directory are not masked. |
| environment rules | Restricted environment block, with `SYSTEMROOT` retained for Windows networking support | Does not filter inherited state beyond the supplied environment. |
| `net=` | AppContainer network capabilities | No rule means no outbound network. Public access grants `internetClient`; private network access grants `privateNetworkClientServer`. The OS does not filter host, port, or protocol. |
| process lifetime | `KILL_ON_JOB_CLOSE` Job Object | The job also applies UI restrictions. |

When `py-sandbox=false`, host, port, and protocol restrictions are not provided by the OS, so the provider must
warn. AppContainer blocks loopback connections regardless of capability; a rule that allows loopback cannot be
honored. The shared SSE socket is passed into the child so the sandbox does not need a loopback exception.

The interpreter and virtual environment are read-only grants to the `pysandboxesRuntime` capability SID. These
grants persist and apply only to processes carrying that capability. Other project paths, working directories,
and site-package paths outside the interpreter and venv are per-run package SID grants, removed on exit. This
prevents a permanent runtime capability grant from exposing project data to future runs.

Windows access-control lists are shared state. The implementation serializes ACL changes with a file lock and
records temporary masks in a journal so concurrent runs do not overwrite one another's ACL changes. If a
machine-wide Python runtime is not readable and the user cannot change its ACL, an administrator must grant the
runtime capability read access once. The command reported by the provider has this form:

```powershell
icacls <runtime-directory> /grant *<pysandboxesRuntime-SID>:(OI)(CI)RX /T
```

Every ACL operation must be checked. A failed grant is fatal; do not use `icacls /C`, which can silently skip
errors.

## Requirements and local validation

The provider requires Windows 8 or later (`userenv.CreateAppContainerProfile`) and targets a Windows host. This
repository does not provide a Docker, Podman, or Kubernetes deployment for this provider; the local Linux VM
workflow below uses Docker or Podman only to run the Windows VM.

Normal use does not require an administrator account. The Windows account running the sandbox needs:

- Read and execute access to the Python interpreter, its standard library, and the virtual environment.
- Permission to change the DACL on paths that the provider must expose or mask for a run. A user normally has
  this permission on paths they own; protected paths owned by another account may require an administrator to
  adjust their ACLs.
- Write access to its `%LOCALAPPDATA%\pysandboxes\appcontainer` state directory, created by the provider.

The provider changes DACLs only; it does not require SACL privileges. It creates temporary per-run grants on
exposed paths and removes them when the run ends. For Python runtime paths, it grants read and execute access to
the `pysandboxesRuntime` capability SID and caches that grant. If the account cannot change the runtime DACL,
an administrator must apply the one-time grant shown by the error message. Machine-wide Python installation is
optional; the local VM uses it for reproducibility and copies the runtime into the standard user's profile.

Windows network enforcement has narrower rights and features than the Linux providers. With no allowed `net=`
rule, AppContainer blocks outbound network access. An allowed rule selects broad public Internet or private
network capability. Host, port, and protocol checks remain in the Python guard and can be bypassed by native
code; AppContainer itself also blocks loopback. This provider does not offer OS-level per-host or per-port
filtering for standard users.

The reproducible local validation setup uses Linux, Docker or Podman, `/dev/kvm`, about 40 GB of disk, 4 GB RAM,
and around 30 minutes for the first Windows 11 Pro VM installation.

The Makefile workflow is:

```bash
make windows-vm          # Create/start the local Windows VM and provision SSH/Python
make windows-tests       # Copy the test inputs and run provider suites as admin and sbuser
make windows-vm-stop     # Stop the VM
make windows-vm-clean    # Remove the VM and its local key/state
```

`windows-tests` runs with `PYSANDBOXES_FAIL_ON_SKIP=1`, both as the VM administrator and as the standard user
`sbuser`. It stages repository files over SSH rather than relying on a VM network share. The VM recipe installs
OpenSSH, provisions a separate `sbuser` account, and installs Python machine-wide. The test target copies that
runtime into `sbuser`'s profile so the standard user can grant its AppContainer capability access recursively.

Release support is gated on the Windows integration tests and shared provider suites passing in both CI and this
VM. The `win32` provider registration is present on this branch so CI exercises it; do not publish the provider
until the Windows CI job passes.

## Known limits

- Windows system paths granted to `ALL APPLICATION PACKAGES` can remain readable. The more restrictive LPAC
  mode does not start the tested Python runtime.
- `ignore=` masks paths that exist at launch; parent directory names may still be listed.
- `net=` can select no network, public Internet, or private network access. Host, port, and protocol filtering
  remain Python-layer checks; loopback is always blocked by AppContainer.
- AppContainers can read much of `HKLM`; registry access is not mapped from file rules.
- Runtime capability grants persist. Per-run package SID ACLs and service window station/desktop ACLs exist
  only while a run is active.
- A standard user's uv-managed Python minor-version junction can fail traversal on recent Windows. The local VM
  setup installs Python machine-wide to avoid that unrelated uv behavior.
