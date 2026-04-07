# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Prepare guest bootstrap and cloud-init data for QEMU provider.

Puts bootstrap and config on a NoCloud ISO; guest accesses pysandboxes
via virtio-9p mount from the host. Config is embedded directly in the ISO
as config.pkl, avoiding a separate HTTP server.
"""

import logging
import os
import pickle
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GUEST_CIDATA_MOUNT = "/mnt/cidata"
GUEST_VENV_MOUNT = "/mnt/venv-packages"  # 9p mount for host venv site-packages
GUEST_PYSANDBOXES_MOUNT = (
    "/mnt/pysandboxes-src"  # 9p mount for pysandboxes package parent
)
VENV_9P_TAG = "venv"
PYSANDBOXES_9P_TAG = "pysandboxes_src"
BOOTSTRAP_HTTP_NAME = "bootstrap_http.py"
CONFIG_PKL_NAME = "config.pkl"
NOCLOUD_ISO = "nocloud.iso"
CIDATA_LABEL = "cidata"


def _config_paths_to_str(obj: Any) -> Any:
    """Recursively replace Path with str for cross-version pickle compatibility."""
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "_asdict") and hasattr(obj, "_fields"):
        return type(obj)(
            **{k: _config_paths_to_str(v) for k, v in obj._asdict().items()}
        )
    if isinstance(obj, dict):
        return {k: _config_paths_to_str(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(_config_paths_to_str(x) for x in obj)
    return obj


def _write_config_pkl(temp: Path, process_config: Any) -> None:
    """Serialize process_config to temp/config.pkl with Path->str conversion."""
    safe_config = _config_paths_to_str(process_config)
    (temp / CONFIG_PKL_NAME).write_bytes(
        pickle.dumps(safe_config, protocol=pickle.HIGHEST_PROTOCOL)
    )


def _write_bootstrap_http(dest: Path) -> None:
    """Write bootstrap_http.py: read config from cidata ISO mount."""
    script = (
        "#!/usr/bin/env python3\n"
        '"""Run inside guest: read config from cidata ISO, apply iptables, run SSE server."""\n'
        "import os\n"
        "import subprocess\n"
        "import sys\n"
        "import traceback\n"
        "from pathlib import Path\n"
        "\n"
        "def _trace(msg: str) -> None:\n"
        '    print("[pysandbox-bootstrap] " + msg, file=sys.stderr, flush=True)\n'
        "\n"
        '_trace("starting bootstrap_http.py")\n'
        '_trace("sys.path=%s" % sys.path)\n'
        "\n"
        "# Config is embedded in the cidata ISO at a known path\n"
        'config_path = Path("/mnt/cidata/config.pkl")\n'
        "if not config_path.is_file():\n"
        '    _trace("ERROR: config.pkl not found at %s" % config_path)\n'
        "    sys.exit(1)\n"
        '_trace("config_path=%s size=%s" % (config_path, config_path.stat().st_size))\n'
        "\n"
        '_trace("importing pysandboxes.remote.sse_client_subprocess_daemon ...")\n'
        "try:\n"
        "    import pysandboxes.remote.sse_client_subprocess_daemon  # noqa: F401\n"
        '    _trace("import pysandboxes.remote.sse_client_subprocess_daemon OK")\n'
        "except Exception as e:\n"
        '    _trace("import FAILED: %s" % e)\n'
        "    traceback.print_exc(file=sys.stderr)\n"
        '    _trace("sys.path at failure=%s" % sys.path)\n'
        "    raise\n"
        "\n"
        "import pickle as _pkl\n"
        "\n"
        "def _restore_config_paths(obj):\n"
        '    """Restore Path fields (host sent str to avoid pathlib._local across Python versions)."""\n'
        '    _path_fields = frozenset(("root_path", "learning_path"))\n'
        '    if hasattr(obj, "_asdict") and hasattr(obj, "_replace"):\n'
        "        d = obj._asdict()\n"
        "        restored = {k: Path(d[k]) if k in _path_fields and isinstance(d.get(k), str) else _restore_config_paths(v) for k, v in d.items()}\n"
        "        return type(obj)(**restored)\n"
        "    if isinstance(obj, dict):\n"
        "        return {k: _restore_config_paths(v) for k, v in obj.items()}\n"
        "    if isinstance(obj, (list, tuple)):\n"
        "        return type(obj)(_restore_config_paths(x) for x in obj)\n"
        "    return obj\n"
        "\n"
        '_trace("loading pickle from %s ..." % config_path)\n'
        "try:\n"
        '    with open(config_path, "rb") as f:\n'
        "        process_config = _pkl.load(f)\n"
        "    process_config = _restore_config_paths(process_config)\n"
        '    _trace("pickle load OK, process_config type=%s" % type(process_config).__name__)\n'
        "except Exception as e:\n"
        '    _trace("pickle load FAILED: %s" % e)\n'
        "    traceback.print_exc(file=sys.stderr)\n"
        "    raise\n"
        "\n"
        'rules = getattr(process_config, "netfilter_rules", ()) or ()\n'
        "if rules:\n"
        "    subprocess.run(\n"
        '        ["iptables-restore", "--noflush"],\n'
        '        input="\\n".join(rules).encode(),\n'
        "        check=False,\n"
        "    )\n"
        "# Use writable work dir so tests can write to ./tmp (e.g. tmp/test.remove)\n"
        '_work_dir = "/tmp/pysandbox_work"\n'
        "os.makedirs(_work_dir, exist_ok=True)\n"
        'os.makedirs(os.path.join(_work_dir, "tmp"), exist_ok=True)\n'
        "os.chdir(_work_dir)\n"
        '_trace("importing run_guest ...")\n'
        "from pysandboxes.remote.main_sandbox import run_guest\n"
        '_trace("calling run_guest()")\n'
        "sys.exit(run_guest(process_config))\n"
    )
    (dest / BOOTSTRAP_HTTP_NAME).write_text(script, encoding="utf-8")


GUEST_BOOTSTRAP_SCRIPT = "/tmp/run_pysandbox_bootstrap.sh"


def _bootstrap_script_content(use_venv_9p: bool, use_pysandboxes_9p: bool) -> str:
    """Build the guest bootstrap script (avoids YAML quoting issues in runcmd)."""
    lines = [
        "#!/bin/bash",
        "set -e",
        "echo '[pysandbox-bootstrap] starting script' >&2",
        "",
    ]

    # Load 9p kernel modules if any 9p share is needed
    if use_venv_9p or use_pysandboxes_9p:
        lines.extend(
            [
                "echo '[pysandbox-9p] loading 9p modules' >&2",
                "modprobe 9pnet_virtio 2>/dev/null || true",
                "modprobe 9p 2>/dev/null || true",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "echo '[pysandbox-bootstrap] installing Python deps' >&2",
                "apt-get update -qq && apt-get install -y -qq python3-pip",
                "pip3 install --break-system-packages 'aiohttp>=3.12' 'aiohttp-sse-client>=0.2.1' 'fastapi>=0.115' 'uvicorn>=0.34' 'netifaces>=0.11' 'tblib>=3.1'",
                "",
            ]
        )

    if use_pysandboxes_9p:
        lines.extend(
            [
                f"mkdir -p {GUEST_PYSANDBOXES_MOUNT}",
                f"echo '[pysandbox-9p] mounting tag={PYSANDBOXES_9P_TAG} to {GUEST_PYSANDBOXES_MOUNT}' >&2",
                f"mount -t 9p -o trans=virtio,version=9p2000.L {PYSANDBOXES_9P_TAG} {GUEST_PYSANDBOXES_MOUNT} 2>&1 | sed 's/^/[pysandbox-9p] /' >&2 || echo '[pysandbox-9p] pysandboxes mount failed' >&2",
                f"(mountpoint -q {GUEST_PYSANDBOXES_MOUNT} && echo '[pysandbox-9p] pysandboxes mountpoint OK' >&2) || echo '[pysandbox-9p] pysandboxes mountpoint FAILED' >&2",
                "",
            ]
        )

    if use_venv_9p:
        lines.extend(
            [
                f"mkdir -p {GUEST_VENV_MOUNT}",
                f"echo '[pysandbox-9p] mounting tag={VENV_9P_TAG} to {GUEST_VENV_MOUNT}' >&2",
                f"mount -t 9p -o trans=virtio,version=9p2000.L {VENV_9P_TAG} {GUEST_VENV_MOUNT} 2>&1 | sed 's/^/[pysandbox-9p] /' >&2 || echo '[pysandbox-9p] venv mount failed' >&2",
                f"(mountpoint -q {GUEST_VENV_MOUNT} && echo '[pysandbox-9p] venv mountpoint OK' >&2) || echo '[pysandbox-9p] venv mountpoint FAILED' >&2",
                "dmesg | tail -20 | grep -iE '9p|virtio_9p' 2>/dev/null | sed 's/^/[pysandbox-9p] dmesg: /' >&2 || true",
                "",
            ]
        )

    pypath_parts = []
    if use_pysandboxes_9p:
        pypath_parts.append(GUEST_PYSANDBOXES_MOUNT)
    if use_venv_9p:
        pypath_parts.append(GUEST_VENV_MOUNT)
    pypath = ":".join(pypath_parts) if pypath_parts else ""

    lines.extend(
        [
            f"mkdir -p {GUEST_CIDATA_MOUNT}",
            f"mount /dev/vdb {GUEST_CIDATA_MOUNT} || mount LABEL={CIDATA_LABEL} {GUEST_CIDATA_MOUNT} || true",
            f"echo '[pysandbox-bootstrap] exec python PYTHONPATH={pypath}' >&2",
            f"env PYTHONPATH={pypath} python3 {GUEST_CIDATA_MOUNT}/{BOOTSTRAP_HTTP_NAME} || true",
            "poweroff -f",
        ]
    )
    return "\n".join(lines)


def _create_nocloud_iso(
    temp: Path,
    venv_site_packages_path: Path | None = None,
    use_pysandboxes_9p: bool = False,
) -> Path:
    """Create NoCloud iso with user-data, meta-data, bootstrap and embedded config.pkl.

    If venv_site_packages_path is set, cloud-init will mount the host venv via 9p.
    If use_pysandboxes_9p is True, cloud-init will mount pysandboxes source via 9p.
    Config is embedded as config.pkl in the ISO (no HTTP server needed).
    Returns the path to the NoCloud iso.
    """
    use_venv_9p = venv_site_packages_path is not None
    script_content = _bootstrap_script_content(use_venv_9p, use_pysandboxes_9p)
    # Indent script for YAML literal block (each line prefixed with 6 spaces)
    script_yaml = "\n".join("      " + line for line in script_content.splitlines())
    user_data = f"""#cloud-config
# Use only NoCloud (no wait for EC2/OpenStack metadata).
datasource_list: [NoCloud]
datasource:
  NoCloud:
    max_wait: 0

# Fallback: if guest has no NIC or DHCP is slow, wait-online times out in 5s.
bootcmd:
  - mkdir -p /etc/systemd/system/systemd-networkd-wait-online.service.d
  - printf '[Service]\\nTimeoutStartSec=5\\n' > /etc/systemd/system/systemd-networkd-wait-online.service.d/timeout.conf

write_files:
  - path: /etc/systemd/system/systemd-networkd-wait-online.service.d/timeout.conf
    content: |
      [Service]
      TimeoutStartSec=5
    permissions: '0644'
  - path: {GUEST_BOOTSTRAP_SCRIPT}
    content: |
{script_yaml}
    permissions: '0755'

# QEMU -nic user provides DHCP; match en* (e.g. enp0s2 from virtio-net-pci).
network:
  version: 2
  ethernets:
    id0:
      match:
        name: en*
      optional: true
      dhcp4: true

# Stop gettys then run bootstrap script (script does mount, exec python).
runcmd:
  - systemctl stop serial-getty@ttyS0.service getty@ttyS0.service getty@tty1.service || true
  - systemctl mask serial-getty@ttyS0.service getty@ttyS0.service getty@tty1.service || true
  - {GUEST_BOOTSTRAP_SCRIPT}
"""
    meta_data = "instance-id: pysandboxes-qemu\nlocal-hostname: pysandbox\n"
    (temp / "user-data").write_text(user_data, encoding="utf-8")
    (temp / "meta-data").write_text(meta_data, encoding="utf-8")
    _root = sorted(os.listdir(temp))
    logger.info("qemu bootstrap: temp before ISO root=%s", _root)
    iso_path = temp / NOCLOUD_ISO
    graft_args = [
        "-graft-points",
        "user-data=user-data",
        "meta-data=meta-data",
        f"{BOOTSTRAP_HTTP_NAME}={BOOTSTRAP_HTTP_NAME}",
        f"{CONFIG_PKL_NAME}={CONFIG_PKL_NAME}",
    ]
    for cmd in ("genisoimage", "mkisofs"):
        try:
            subprocess.run(
                [cmd, "-o", NOCLOUD_ISO, "-V", CIDATA_LABEL, "-J", "-r"] + graft_args,
                check=True,
                capture_output=True,
                timeout=60,
                cwd=temp,
            )
            return iso_path
        except FileNotFoundError:
            continue
    raise RuntimeError("genisoimage or mkisofs required for QEMU guest bootstrap")


def prepare_guest_env(
    temp: Path,
    process_config: Any,
    venv_site_packages_path: Path | None = None,
    use_pysandboxes_9p: bool = False,
) -> Path:
    """Prepare NoCloud ISO for the guest (bootstrap + config embedded in ISO).

    Serializes process_config to config.pkl and includes it in the cloud-init ISO.
    The guest accesses pysandboxes via virtio-9p (no copy into ISO).
    Returns the path to the NoCloud iso.
    """
    logger.debug(
        "qemu bootstrap: prepare_guest_env temp=%s venv_9p=%s pysandboxes_9p=%s",
        temp,
        venv_site_packages_path,
        use_pysandboxes_9p,
    )
    _write_config_pkl(temp, process_config)
    _write_bootstrap_http(temp)
    iso_path = _create_nocloud_iso(temp, venv_site_packages_path, use_pysandboxes_9p)
    logger.debug(
        "qemu bootstrap: ISO created %s size=%s", iso_path, iso_path.stat().st_size
    )
    return iso_path
