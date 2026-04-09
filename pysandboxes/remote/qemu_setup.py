# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Prepare guest bootstrap and cloud-init data for QEMU provider.

NoCloud ISO contains the bootstrap script, pipe_name, and 9p_mounts (one line
per "tag guest_path"). The guest mounts each tag at its path, then runs
main_sandbox --_named-pipe (same flow as bwrap/unshare).
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GUEST_CIDATA_MOUNT = "/mnt/cidata"
GUEST_RUN_MOUNT = "/mnt/pysandbox_run"
GUEST_CONFIG_MOUNT = "/mnt/pysandbox_config"
PIPE_NAME_FILE = "pipe_name"
NOCLOUD_ISO = "nocloud.iso"
CIDATA_LABEL = "cidata"
GUEST_BOOTSTRAP_SCRIPT = "/tmp/run_pysandbox_bootstrap.sh"
NINEP_MOUNTS_FILE = "9p_mounts"
PYTHON_EXE_FILE = "python_exe"
PYTHON_VERSION_FILE = "python_version"


def _bootstrap_script_content(
    mounts: list[tuple[str, str]],
    pipe_run_guest_path: str,
    python_version: str,
    python_exe: str | None = None,
    config_guest_path: str | None = None,
    guest_cwd: str | None = None,
) -> str:
    """Build the guest bootstrap script: mount cidata,
    verify Python version (no install), then run main_sandbox
    --_named-pipe (config from 9p or pipe)."""
    lines = [
        "#!/bin/bash",
        "set -e",
        "echo '[pysandbox-bootstrap] starting' >&2",
        "",
        "# Mount NoCloud cidata first so 9p_mounts, pipe_name and python_version are available",
        f"mkdir -p {GUEST_CIDATA_MOUNT}",
        f"mount /dev/vdb {GUEST_CIDATA_MOUNT} 2>/dev/null || mount LABEL={CIDATA_LABEL} {GUEST_CIDATA_MOUNT} || true",
        "",
        "echo '[pysandbox-9p] loading 9p modules' >&2",
        "modprobe 9pnet_virtio 2>/dev/null || true",
        "modprobe 9p 2>/dev/null || true",
        "",
    ]
    if mounts:
        lines.append("echo '[pysandbox-9p] mounting file_rules shares' >&2")
        lines.append("while read -r tag path; do")
        lines.append('  [ -z "$tag" ] && continue')
        lines.append('  mkdir -p "$path"')
        lines.append('  echo "[pysandbox-9p] $tag -> $path" >&2')
        lines.append(
            "  mount -t 9p -o trans=virtio,version=9p2000.L "
            '"$tag" "$path" 2>&1 | sed \'s/^/[pysandbox-9p] /\' >&2 || true'
        )
        lines.append("done < " + f"{GUEST_CIDATA_MOUNT}/{NINEP_MOUNTS_FILE}")
        lines.append("")
    # Required Python version from host; image must already provide it (no install)
    lines.extend(
        [
            "PYTHON_VERSION=$(cat "
            + f"{GUEST_CIDATA_MOUNT}/{PYTHON_VERSION_FILE}"
            + " 2>/dev/null | tr -d '\\n' || echo '')",
            'echo "[pysandbox-bootstrap] required Python version: ${PYTHON_VERSION:-none}" >&2',
            "PYTHON_EXE=''",
            # Prefer host binary path (9p-mounted) if present
            "HOST_EXE=$(cat "
            + f"{GUEST_CIDATA_MOUNT}/{PYTHON_EXE_FILE}"
            + " 2>/dev/null | tr -d '\\n' || true)",
            '[ -n "$HOST_EXE" ] && [ -f "$HOST_EXE" ] && PYTHON_EXE=$HOST_EXE',
            # Else use guest python (same major.minor as required)
            'if [ -z "$PYTHON_EXE" ] && [ -n "$PYTHON_VERSION" ]; then',
            "  for py in python${PYTHON_VERSION} python3.${PYTHON_VERSION#*.}; do",
            '    if command -v "$py" >/dev/null 2>&1; then PYTHON_EXE=$py; break; fi',
            "  done",
            "fi",
            '[ -z "$PYTHON_EXE" ] && PYTHON_EXE=python3',
            'echo "[pysandbox-bootstrap] PYTHON_EXE=$PYTHON_EXE" >&2',
            # Verify version: image must have expected Python (no install)
            'ACTUAL_VERSION="$("$PYTHON_EXE" -c \'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")\' 2>/dev/null)"',
            'if [ -z "$ACTUAL_VERSION" ]; then',
            "  echo '[pysandbox-bootstrap] ERROR: could not get Python version from' \"$PYTHON_EXE\" >&2",
            "  poweroff -f",
            "fi",
            'if [ "$ACTUAL_VERSION" != "$PYTHON_VERSION" ]; then',
            "  echo '[pysandbox-bootstrap] ERROR: expected Python $PYTHON_VERSION, image has Python $ACTUAL_VERSION' >&2",
            "  poweroff -f",
            "fi",
            'echo "[pysandbox-bootstrap] Python version OK: $ACTUAL_VERSION" >&2',
            "",
        ]
    )
    pypath = ":".join(m[1] for m in mounts) if mounts else ""
    guest_cwd = guest_cwd or (mounts[0][1] if mounts else "/")
    if config_guest_path:
        lines.extend(
            [
                f'CONFIG_PATH="{config_guest_path}"',
                "echo '[pysandbox-bootstrap] exec main_sandbox --_named-pipe '\"'\"'$CONFIG_PATH'\"'\"'' >&2",
            ]
        )
    else:
        lines.extend(
            [
                "PIPE_NAME=$(cat "
                + f"{GUEST_CIDATA_MOUNT}/{PIPE_NAME_FILE}"
                + " 2>/dev/null | tr -d '\\n' || echo '')",
                'if [ -z "$PIPE_NAME" ]; then echo "[pysandbox-bootstrap] ERROR: pipe_name not found on cidata" >&2; poweroff -f; fi',
                f'CONFIG_PATH={pipe_run_guest_path}/"$PIPE_NAME"',
                "echo '[pysandbox-bootstrap] exec main_sandbox --_named-pipe '\"'\"'$CONFIG_PATH'\"'\"'' >&2",
            ]
        )
    lines.extend(
        [
            f'cd "{guest_cwd}" || true',
            ("env PYTHONPATH=" + pypath + " " if pypath else "env ")
            + '"$PYTHON_EXE" -m pysandboxes.remote.main_sandbox --_named-pipe "$CONFIG_PATH" || true',
            "poweroff -f",
        ]
    )
    return "\n".join(lines)


def _create_nocloud_iso(
    temp: Path,
    process_config: Any,
    mounts: list[tuple[str, str]],
    pipe_basename: str,
    pipe_run_guest_path: str,
    python_version: str,
    python_exe: str | None = None,
    config_guest_path: str | None = None,
) -> Path:
    """Create NoCloud ISO with user-data, meta-data, bootstrap script, 9p_mounts, pipe_name, python_version, python_exe (version is verified in guest, not installed)."""
    all_rules = getattr(process_config, "all_rules", None)
    root_path = getattr(all_rules, "root_path", None)
    guest_cwd = str(root_path.resolve()) if isinstance(root_path, Path) else None
    script_content = _bootstrap_script_content(
        mounts,
        pipe_run_guest_path,
        python_version,
        python_exe,
        config_guest_path,
        guest_cwd=guest_cwd,
    )
    script_yaml = "\n".join("      " + line for line in script_content.splitlines())
    (temp / PIPE_NAME_FILE).write_text(pipe_basename.strip(), encoding="utf-8")
    (temp / PYTHON_VERSION_FILE).write_text(python_version + "\n", encoding="utf-8")
    if python_exe:
        (temp / PYTHON_EXE_FILE).write_text(python_exe + "\n", encoding="utf-8")
    (temp / NINEP_MOUNTS_FILE).write_text(
        "\n".join(f"{tag} {path}" for tag, path in mounts) + ("\n" if mounts else ""),
        encoding="utf-8",
    )
    user_data = f"""#cloud-config
datasource_list: [NoCloud]
datasource:
  NoCloud:
    max_wait: 0

bootcmd:
  - mkdir -p /etc/systemd/system/systemd-networkd-wait-online.service.d
  - printf '[Service]\\nTimeoutStartSec=5\\n' > /etc/systemd/system/systemd-networkd-wait-online.service.d/timeout.conf

write_files:
  - path: /etc/systemd/system/systemd-networkd-wait-online.service.d/timeout.conf
    content: |
      [Service]
      TimeoutStartSec=5
    permissions: '0644'
  - path: /etc/resolv.conf
    content: |
      nameserver 10.0.2.3
    permissions: '0644'
  - path: {GUEST_BOOTSTRAP_SCRIPT}
    content: |
{script_yaml}
    permissions: '0755'

network:
  version: 2
  ethernets:
    id0:
      match:
        name: en*
      optional: true
      dhcp4: true

runcmd:
  - systemctl stop serial-getty@ttyS0.service getty@ttyS0.service getty@tty1.service || true
  - systemctl mask serial-getty@ttyS0.service getty@ttyS0.service getty@tty1.service || true
  - {GUEST_BOOTSTRAP_SCRIPT}
"""
    meta_data = "instance-id: pysandboxes-qemu\nlocal-hostname: pysandbox\n"
    (temp / "user-data").write_text(user_data, encoding="utf-8")
    (temp / "meta-data").write_text(meta_data, encoding="utf-8")
    iso_path = temp / NOCLOUD_ISO
    graft_args = [
        "-graft-points",
        "user-data=user-data",
        "meta-data=meta-data",
        f"{PIPE_NAME_FILE}={PIPE_NAME_FILE}",
        f"{PYTHON_VERSION_FILE}={PYTHON_VERSION_FILE}",
        f"{NINEP_MOUNTS_FILE}={NINEP_MOUNTS_FILE}",
    ]
    if python_exe:
        graft_args.append(f"{PYTHON_EXE_FILE}={PYTHON_EXE_FILE}")
    for cmd in ("genisoimage", "mkisofs"):
        try:
            subprocess.run(
                [
                    cmd,
                    "-o",
                    NOCLOUD_ISO,
                    "-V",
                    CIDATA_LABEL,
                    "-J",
                    "-r",
                ]
                + graft_args,
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
    pipe_path: Path,
    mounts: list[tuple[str, str]],
    pipe_run_guest_path: str = GUEST_RUN_MOUNT,
    python_version: str = "3.11",
    python_exe: str | None = None,
    config_guest_path: str | None = None,
) -> Path:
    """Prepare NoCloud ISO: bootstrap script, 9p_mounts, pipe_name, python_version, optional python_exe.

    mounts: list of (9p_tag, guest_path) so the guest mounts each tag at that path.
    pipe_run_guest_path: guest path where the run dir (with FIFO) is mounted.
    python_version: host Python major.minor (e.g. 3.13); guest must already have this version (verified, not installed).
    python_exe: host sys.executable path (9p-mounted in guest); used when available, else guest python is checked.
    config_guest_path: when set, guest reads config from this 9p path (e.g. /mnt/pysandbox_config/config.pkl) instead of pipe.
    Returns the path to the NoCloud ISO.
    """
    logger.debug(
        "qemu bootstrap: prepare_guest_env temp=%s mounts=%s pipe=%s python=%s",
        temp,
        len(mounts),
        pipe_path.name,
        python_version,
    )
    return _create_nocloud_iso(
        temp,
        process_config,
        mounts,
        pipe_path.name,
        pipe_run_guest_path,
        python_version,
        python_exe,
        config_guest_path,
    )
