# Images on Docker Hub

Each release publishes five images to Docker Hub, built from the wheel published on the same run (see
[Releasing](release.md)). Use them to run `python-sb` in a container without building anything locally.

| Image | Provider it carries | Contents |
|---|---|---|
| `docker.io/pprados/python-sb` | `none`, `subprocess` | Python and the `pysandboxes` wheel |
| `docker.io/pprados/python-sb-landlock` | `landlock` | the base image; Landlock is a kernel LSM, no package needed |
| `docker.io/pprados/python-sb-unshare` | `unshare` | the base image plus `iptables`, `iproute2` and `slirp4netns` |
| `docker.io/pprados/python-sb-bwrap` | `bwrap` | the base image plus `bubblewrap`, `slirp4netns` and `iptables` |
| `docker.io/pprados/python-sb-qemu` | `qemu` | the base image plus QEMU, `genisoimage` and the guest VM image |

Each image holds every tool its provider invokes, which is the hard part to get right by hand: without `iptables`,
for instance, a bwrap profile with socket rules refuses to start. There is no `python-sb-firejail` on purpose:
firejail is a setuid program, ill-suited to a container.

## Tags

The images are `linux/amd64`, published for Python 3.11, 3.12, 3.13 and 3.14. They are tagged in the manner of the
official `python` images, since each is Python with pysandboxes: `pprados/python-sb:3.14` is to `python:3.14` what
the sandbox is to Python. Each release pushes, for every image:

| Tag | Example | Moves? | Pushed for |
|---|---|---|---|
| `<python>-<version>` | `3.12-0.1.0` | never | every release and every Python |
| `<version>` | `0.1.0` | never | every release, Python 3.14 |
| `<python>` | `3.12` | to each final release | final releases only, every Python |
| `3`, `latest` | `latest` | to each final release | final releases only, Python 3.14 |

A pre-release (`a`, `b`, `rc`) never moves `latest`, `3` nor `<python>`, so a plain `docker pull` never gets one.
To be sure that what runs stays the same, use `<python>-<version>`, or the digest. Pre-releases up to `0.1.0b8` were
tagged `<version>` only. The qemu image matches its guest VM to its Python, so take the Python your
code needs rather than the default.

## Pulling

```bash
VERSION=0.1.0b8
docker pull docker.io/pprados/python-sb-unshare:$VERSION
```

With Podman, give the full name: a short name such as `pprados/python-sb-unshare` depends on the registries
configured on the host.

```bash
podman pull docker.io/pprados/python-sb-unshare:$VERSION
```

To check that a pulled image is the published one, compare its digest with the one listed in the summary of the
release run:

```bash
docker inspect --format '{{index .RepoDigests 0}}' docker.io/pprados/python-sb-unshare:$VERSION
```

## Running

Each provider needs the same container options as with a locally built image. Mount the code to run on `/app`:

```bash
# landlock: no privilege
docker run -it --rm -v "$(pwd)":/app -w /app \
  docker.io/pprados/python-sb-landlock:$VERSION \
  sh -c 'OS_SANDBOX=landlock python-sb my_script.py'

# unshare: privileged, bridge network
docker run -it --rm --privileged --network bridge -v "$(pwd)":/app -w /app \
  docker.io/pprados/python-sb-unshare:$VERSION \
  sh -c 'OS_SANDBOX=unshare python-sb my_script.py'

# bwrap: privileged
docker run -it --rm --privileged -v "$(pwd)":/app -w /app \
  docker.io/pprados/python-sb-bwrap:$VERSION \
  sh -c 'OS_SANDBOX=bwrap python-sb my_script.py'

# qemu: /dev/kvm when the host has it, TCG emulation otherwise
docker run -it --rm --device /dev/kvm -v "$(pwd)":/app -w /app \
  docker.io/pprados/python-sb-qemu:$VERSION \
  sh -c 'OS_SANDBOX=qemu python-sb my_script.py'
```

The same commands work with `podman` in place of `docker`. The provider pages detail each option:
[LandLock](landlock.md), [Unshare](unshare.md), [Bubblewrap](bwrap.md), [QEMU](qemu.md).

## Kubernetes

Point the pod at the published image and let the cluster pull it, in place of the `imagePullPolicy: Never` used
with images loaded by `make minikube-build-images`:

```yaml
      image: docker.io/pprados/python-sb-unshare:0.1.0b8
      imagePullPolicy: IfNotPresent
```

The pod needs the same privileges as the `docker run` above (see [Unshare](unshare.md#using-with-kubernetes)).
