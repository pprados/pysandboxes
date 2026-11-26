# docker-sandbox provider (`os-sandbox=docker-sandbox`)

The sandboxed code runs in a micro-VM of [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/) (`sbx`): its own
guest kernel, a template as the root. The VM boundary is the isolation; nothing of the host is in the guest unless a
rule exposes it. The provider is Linux only.

## How it works

`python-sb` and the daemon start a launcher (`docker_sandbox_launcher.py`) that follows a plan the provider computed:

1. `sbx create shell` with the template, the mounts, the published port and the CPU and memory limits.
2. `sbx policy allow|deny network --sandbox <name>` for each translated `net=` rule, then `sbx policy check` of every
   allowed destination and of a canary name no profile allows. Any mismatch removes the sandbox and stops the start.
3. One `sbx exec -u root` that checks the Python version, masks what `ignore=` names, creates the user `sandbox`
   (uid and gid 2000) and runs the payload through `setpriv` with no capability and `no_new_privs`, under `env -i`.
4. A second `sbx exec` held open as a reaper: if the launcher dies, it kills the payload. The launcher removes the
   sandbox when the run ends.

- **Guest template**: `pysandboxes-guest:<python minor>`, built by `make build-image-docker-sandbox`. It holds the
  interpreter (installed with `uv python install`) and the dependencies of pysandboxes, no `sudo`, and a
  `/etc/ssl/cert.pem` so the interpreter finds the certificates. The package of the host is mounted read-only at its
  host path (or at `/opt/pysb/pysandboxes` when that path lies in a directory the image owns), so what runs is the code
  of the host. The guest must run the Python minor of the host: another one stops with exit 72.
- **Files**: `expose-ro` is a read-only mount enforced by the host side, `expose-rw` a read-write mount at the same
  path. The first read-write directory is the primary workspace of the sandbox; without one, a private empty
  directory of the run. A directory the image owns (`/usr`, `/etc`, ...) and a path that does not exist are not mounted.
  `ignore=` hides files with `mount(2)` from the root step, before the privileges are dropped: the payload cannot undo it.
- **Channel**: the HTTP and SSE port chosen by the daemon is published by `sbx` (`-p port:port`) and the guest listens
  on `0.0.0.0`. `remote-endpoint=unix` is an error, `auto` uses TCP. The config goes from the host FIFO to the standard
  input of the payload, never to a disk.
- **Environment**: the payload runs under `env -i` with the variables the rules grant. Its home is the one of the
  `sandbox` entry of `/etc/passwd`, so `os.path.expanduser` and `getpass.getuser` work.

## Prerequisites

- `sbx` 0.51.0 or later, signed in (`sbx login`), its daemon running, a network policy preset (`sbx policy init
  deny-all`). `unavailable_reason()` checks them without prompting.
- KVM for the micro-VM, as `sbx` needs.
- The guest template: `make build-image-docker-sandbox`.

## Profile

```
os-sandbox=docker-sandbox
docker-sandbox.cpus=2
docker-sandbox.mem=2g
docker-sandbox.template=pysandboxes-guest:3.15
docker-sandbox.python=/usr/local/bin/python
docker-sandbox.proxy=false
```

| Key | Default | Meaning |
|---|---|---|
| `template` | `pysandboxes-guest:<python minor>`, or `PYSANDBOXES_DOCKER_SANDBOX_TEMPLATE` | OCI reference of the guest template |
| `python` | `/usr/local/bin/python` | Interpreter of the template |
| `cpus`, `mem` | those of `sbx` | Limits of the micro-VM |
| `proxy` | `false` | Go through the HTTP proxy of the sandbox (`gateway.docker.internal:3128`, `CONNECT` for HTTPS) |

With `proxy=true` the payload keeps `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` and the certificate variables of the sandbox,
and the Python guard gets an implicit rule for the proxy address. `sbx` then replaces the placeholder of a stored secret
(`sbx secret`) with its value in the request headers, so the code can use a key it never holds. Traffic that goes
through the proxy is decrypted with the `Docker Sandboxes Proxy CA`, which the guest trusts. With `proxy=false`, which
is closer to the other providers, no variable is passed and no secret is injected. Code that sets the proxy itself can
still use it in both modes.

## Rule mapping

| Rule | Result |
|---|---|
| `net=ALLOW\|TCP\|host\|port\|OUT` | `sbx policy allow network`: `host:port`; an address that has a pinned name is opened under both |
| `net=DENY\|...` | `sbx policy deny network` (a deny wins over an allow) |
| any host, with or without a port | `**:port`, or `**` |
| a runtime name rule (`net-resolve=runtime`) | `name` and `**.name`, `=name` for the name alone, `*.name` as `**.name` |
| UDP, ports beyond 64 per rule | not translated, reported |
| incoming rules, DNS | not translated; DNS goes through the resolver of `sbx` |

## Limits

- **The network drops, it does not refuse.** `sbx` accepts every handshake and drops what no rule allows: the connection
  succeeds, then the first read ends at once; a name without a rule fails at DNS. A destination counts as reached only
  when the server answers. IP and CIDR rules only apply to connections that name no host.
- **Name based.** A TLS or HTTP connection is judged by its SNI or `Host`, so a name rule is stricter than the profile's
  address rule. The `Host` header inside an undecrypted stream is not checked.
- **UDP stays closed**, and ICMP is blocked, unless the settings of `sbx` enable UDP egress.
- **A Docker account and daemon are prerequisites.** The provider does not run in a pod. In a container it needs the
  conditions of [In a container](#in-a-container).
- **Every start reads the manifest of the `shell` kit from Docker Hub**, even with a local template (`sbx create` prints
  `resolving docker.io/sbx/shell:latest`). The pull limit of the Docker account then applies: a few hundred starts in
  hours end with `429 toomanyrequests`, and the launcher stops with exit code 70 and the message of `sbx`. A test run
  of the integration suite is about 60 starts.
- **Start-up** costs about 3.3 s per sandbox, and a second `sbx exec` per run for the reaper.
- **Credentials**: see the `proxy` option; the injected headers are the only ones changed, not the query or the body.
- Another sandbox with a denied name that shares an address with an allowed one can still be reached in the cases
  Docker lists.

## Running the tests

```bash
make build-image-docker-sandbox
PYSANDBOXES_FAIL_ON_SKIP=1 uv run pytest -rs tests/integration_tests/remote/test_docker_sandbox.py \
    tests/integration_tests/test_usage_with_providers.py tests/integration_tests/test_guards_with_providers.py \
    -k docker-sandbox
```

`provider_skip_reason()` skips the rows when the template is missing. Hosted CI runners are not covered: run these
suites locally before a release, as for `smolvm`.

## In a container

`tests/containers_tests/test_containers.py::test_container_docker_sandbox` runs the provider in a Docker container:
the `sbx` daemon, the login, the guest template, then `tst_usage` with and without `--py-sandbox`. Each condition below
comes from a measured failure of `sbx`:

- **`--privileged` and `/dev/kvm`.** The micro-VM needs the device, and the daemon mounts its image layers.
- **Loop device nodes.** A container has no udev: `scripts/container_docker_sandbox.sh` creates `/dev/loop0..255`
  before the daemon starts, or `sbx create` fails with `could not open loop device`.
- **The glibc of the host.** `/usr/bin/sbx` and `/usr/libexec` are mounted read-only from the host and need its glibc
  (2.43 on Ubuntu 26.04), so `Dockerfile-docker-sandbox` starts from `ubuntu:26.04`, not from `python:*-slim`.
- **`ca-certificates`** in the image, or `sbx login` fails without a message.
- **A Docker account.** `DOCKER_USER` and `DOCKER_PAT` (an access token, not the password) come from the environment of
  the test; the script reads the token on stdin only. With no keychain, `sbx` stores the secret on disk in the
  container, which is removed with it. Use a dedicated token and revoke it afterwards.

```bash
make build-container-image-docker-sandbox
DOCKER_USER=<account> DOCKER_PAT=<token> uv run pytest -rs tests/containers_tests/test_containers.py -k docker_sandbox
```

The test is skipped without `DOCKER_USER`, `DOCKER_PAT`, `/usr/bin/sbx` or `/dev/kvm`. The template is built in every
run (a few minutes): the state of `sbx` lives in the container.
