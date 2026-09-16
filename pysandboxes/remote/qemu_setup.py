# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Prepare guest bootstrap and cloud-init data for QEMU provider.

NoCloud ISO contains the bootstrap script, pipe_name, and 9p_mounts (one line
per "tag guest_path"). The guest mounts each tag at its path, then runs
main_sandbox --_named-pipe (same flow as bwrap/unshare).
"""

import fnmatch
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from ..all_rules import AllRules
from .vm_sse_daemon import VMSSEDaemon

logger = logging.getLogger(__name__)

GUEST_CIDATA_MOUNT = "/mnt/cidata"
GUEST_RUN_MOUNT = "/mnt/pysandbox_run"
GUEST_CONFIG_MOUNT = "/mnt/pysandbox_config"
# Host directory for this QEMU run (9p → ``GUEST_RUN_MOUNT``). Created
# under the system temp directory (honours ``TMPDIR``).
QEMU_HOST_RUN_PREFIX = "pysandboxes-qemu-"
PIPE_NAME_FILE = "pipe_name"
NOCLOUD_ISO = "nocloud.iso"
CIDATA_LABEL = "cidata"
GUEST_BOOTSTRAP_SCRIPT = "/tmp/run_pysandbox_bootstrap.sh"
NINEP_MOUNTS_FILE = "9p_mounts"
PYTHON_EXE_FILE = "python_exe"
PYTHON_VERSION_FILE = "python_version"
IGNORE_OVERLAYS_FILE = "ignore_overlays"


def _qemu_show_boot_console_truthy(all_rules: Any | None) -> bool:
    """Backward-compatible name; logic lives on :class:`VMSSEDaemon`."""
    return VMSSEDaemon.show_boot_console_truthy(all_rules)


def augment_all_rules_for_qemu_run_mount(all_rules: AllRules) -> AllRules:
    """Prepend implicit expose rule for the guest 9p run mount (host ``/tmp/...``, exitcode).

    The dedicated run directory is mounted at `GUEST_RUN_MOUNT`; it is not described
    in the user profile, so guard_files would otherwise deny writes there.
    """
    from ..guard_files import FSExposeRule
    from ..sb_types import ConfigLine

    run_dir = str(GUEST_RUN_MOUNT)
    if not run_dir.endswith("/"):
        run_dir = run_dir + "/"
    run_mount = FSExposeRule(
        path=run_dir,
        write=True,
        config=ConfigLine(
            "<implicit qemu run mount>",
            Path(__file__),
            0,
        ),
    )
    return all_rules._replace(file_rules=(run_mount,) + all_rules.file_rules)


def _resolve_ignore_paths(current_dir: str, ignore_rules: list[Any]) -> list[str]:
    """Resolve ignore rules to paths relative to current_dir (same semantics as bwrap/unshare)."""
    if not ignore_rules:
        return []
    patterns = [r.source for r in ignore_rules]
    result: list[str] = []
    try:
        cur = Path(current_dir).resolve()
        for root, _dirs, files in os.walk(cur):
            root_path = Path(root)
            for name in list(_dirs) + files:
                if any(fnmatch.fnmatch(name, p) for p in patterns):
                    rel = root_path / name
                    try:
                        rel = rel.relative_to(cur)
                    except ValueError:
                        continue
                    result.append(str(rel))
    except OSError:
        pass
    return result


def qemu_ignore_overlay_abs_paths(all_rules: Any, cwd: str) -> list[str]:
    """Absolute host paths to mask with chmod-0 + mount in the guest (parity with bwrap/unshare)."""
    from pysandboxes.guard_files import IgnoreRule

    ignore_rules = [r for r in all_rules.file_rules if isinstance(r, IgnoreRule)]
    rel = _resolve_ignore_paths(cwd, ignore_rules)
    base = Path(cwd).resolve()
    abs_paths = [str((base / p).resolve()) for p in rel]
    return list(dict.fromkeys(abs_paths))


def _bootstrap_script_content(
    mounts: list[tuple[str, str]],
    pipe_run_guest_path: str,
    python_version: str,
    python_exe: str | None = None,
    config_guest_path: str | None = None,
    guest_cwd: str | None = None,
    *,
    bootstrap_verbose: bool = False,
) -> str:
    """Build the guest bootstrap script: mount cidata,
    verify Python version (no install), then run main_sandbox
    --_named-pipe (config from 9p or pipe)."""
    set_shell = "set -ex" if bootstrap_verbose else "set -e"
    lines = [
        "#!/bin/bash",
        set_shell,
        "# Stop the VM without relying on guest /usr/sbin/poweroff + overlaid /lib (SONAME mismatch",
        "# in nested QEMU): sysrq-o powers off from the kernel; utilities are fallbacks only.",
        "_pysb_halt_guest() {",
        "  sync 2>/dev/null || true",
        "  { echo o > /proc/sysrq-trigger; } 2>/dev/null || true",
        "  poweroff -f 2>/dev/null || true",
        "  halt -fp 2>/dev/null || true",
        "}",
        "",
        "echo '[pysandbox-bootstrap] starting' >&2",
        "",
        "# Serial/ttyS0 is not a TTY; Rich otherwise skips ANSI (FORCE_COLOR / force-color.org).",
        "export TERM=xterm-256color",
        "export FORCE_COLOR=1",
        "",
        "# Ensure guest DNS uses QEMU user net DNS (10.0.2.3) so name resolution works",
        "rm -f /etc/resolv.conf && printf 'nameserver 10.0.2.3\\n' > /etc/resolv.conf",
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
    # Mask ignore= paths (e.g. .env) when Python guards are off (parity with bwrap/unshare overlays)
    ign_file = f"{GUEST_CIDATA_MOUNT}/{IGNORE_OVERLAYS_FILE}"
    lines.append("echo '[pysandbox-bootstrap] ignore overlays' >&2")
    lines.append(f"if [ -f {ign_file} ]; then")
    lines.append('  while IFS= read -r ign_path || [ -n "$ign_path" ]; do')
    lines.append('    [ -z "$ign_path" ] && continue')
    lines.append('    [ -e "$ign_path" ] || continue')
    lines.append('    if [ -d "$ign_path" ]; then')
    lines.append("      ph=$(mktemp -d)")
    lines.append("    else")
    lines.append("      ph=$(mktemp)")
    lines.append("    fi")
    lines.append('    chmod 000 "$ph" 2>/dev/null || true')
    lines.append('    mount --bind "$ph" "$ign_path" 2>&1 | sed \'s/^/[pysandbox-ignore] /\' >&2 || true')
    lines.append(f"  done < {ign_file}")
    lines.append("fi")
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
            "HOST_EXE=$(cat " + f"{GUEST_CIDATA_MOUNT}/{PYTHON_EXE_FILE}" + " 2>/dev/null | tr -d '\\n' || true)",
            # If the host recorded a Python path but 9p did not expose it, do not fall back to
            # the VM image interpreter: PYTHONPATH still points at host site-packages and native
            # extensions (.so) would be the wrong libc → immediate segfault.
            # Conda/venv often use bin/python -> python3.x; virtio-9p may not treat the symlink as
            # -f; resolve to the real binary when possible.
            'if [ -n "$HOST_EXE" ] && [ ! -f "$HOST_EXE" ]; then',
            '  RL=$(readlink -f "$HOST_EXE" 2>/dev/null || true)',
            '  if [ -n "$RL" ] && [ -f "$RL" ]; then HOST_EXE=$RL; fi',
            "fi",
            'if [ -n "$HOST_EXE" ] && [ ! -f "$HOST_EXE" ]; then',
            (
                '  echo "[pysandbox-bootstrap] ERROR: host Python not found at ${HOST_EXE} '
                'after 9p mounts (check mount failures above)." >&2'
            ),
            "  _pysb_halt_guest",
            "  exit 1",
            "fi",
            '[ -n "$HOST_EXE" ] && [ -f "$HOST_EXE" ] && PYTHON_EXE=$HOST_EXE',
            # Else use guest python (same major.minor as required)
            'if [ -z "$PYTHON_EXE" ] && [ -n "$PYTHON_VERSION" ]; then',
            "  for py in python${PYTHON_VERSION} python3.${PYTHON_VERSION#*.}; do",
            '    if command -v "$py" >/dev/null 2>&1; then PYTHON_EXE=$py; break; fi',
            "  done",
            "fi",
            '[ -z "$PYTHON_EXE" ] && PYTHON_EXE=python3',
            'echo "[pysandbox-bootstrap] PYTHON_EXE=$PYTHON_EXE" >&2',
            # Verify version: image must have expected Python (no install).
            # Do not use set -e for the probe: a failing python (missing .so, segfault)
            # would exit the whole script before the error line, leaving cloud-init opaque.
            "set +e",
            (
                'ACTUAL_VERSION="$("$PYTHON_EXE" -c '
                "'import sys; print(\"%d.%d\" % (sys.version_info.major, sys.version_info.minor))' "
                '2>/dev/null)"'
            ),
            "PY_PROBE_RC=$?",
            "set -e",
            'if [ "$PY_PROBE_RC" != 0 ] || [ -z "$ACTUAL_VERSION" ]; then',
            (
                "  echo '[pysandbox-bootstrap] ERROR: Python probe rc='"
                '"$PY_PROBE_RC"'
                "' from '"
                '"$PYTHON_EXE"'
                "'; stderr:' >&2"
            ),
            (
                '  "$PYTHON_EXE" -c '
                "'import sys; print(\"%d.%d\" % (sys.version_info.major, sys.version_info.minor))' "
                "2>&2 || true"
            ),
            "  _pysb_halt_guest",
            "  exit 1",
            "fi",
            'if [ "$ACTUAL_VERSION" != "$PYTHON_VERSION" ]; then',
            (
                "  echo '[pysandbox-bootstrap] ERROR: expected Python $PYTHON_VERSION, "
                "image has Python $ACTUAL_VERSION' >&2"
            ),
            "  _pysb_halt_guest",
            "  exit 1",
            "fi",
            'echo "[pysandbox-bootstrap] Python version OK: $ACTUAL_VERSION" >&2',
            "",
        ]
    )
    pypath = ":".join(m[1] for m in mounts) if mounts else ""
    guest_cwd = guest_cwd or (mounts[0][1] if mounts else "/")
    env_py = "env PYTHONPATH=" + pypath + " " if pypath else "env "
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
                (
                    'if [ -z "$PIPE_NAME" ]; then '
                    'echo "[pysandbox-bootstrap] ERROR: pipe_name not found on cidata" >&2; '
                    "_pysb_halt_guest; exit 1; fi"
                ),
                f'CONFIG_PATH={pipe_run_guest_path}/"$PIPE_NAME"',
                "echo '[pysandbox-bootstrap] exec main_sandbox --_named-pipe '\"'\"'$CONFIG_PATH'\"'\"'' >&2",
            ]
        )
    # Do not use "|| true" on main_sandbox: it masked segfault exit codes (e.g. 139).
    # "-u": the guest's stdout is a pipe (cloud-init), not the serial tty, so CPython
    # block-buffers it. Both sentinels and the program's own output travel on that
    # stdout, so buffering holds the whole window back until the interpreter exits and
    # the caller sees nothing of a long run until it is over. Unbuffered streams it.
    lines.extend(
        [
            f'cd "{guest_cwd}" || true',
            "set +e",
            env_py + '"$PYTHON_EXE" -u -m pysandboxes.remote.main_sandbox --_named-pipe "$CONFIG_PATH"',
            "GUEST_RC=$?",
            "set -e",
            'echo "[pysandbox-bootstrap] main_sandbox finished with exit code $GUEST_RC" >&2',
            # Flush 9p-backed guest_run_dir (exitcode) before halt so the host sees it.
            "_pysb_halt_guest",
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
    """Create NoCloud ISO with user-data, meta-data, bootstrap script, 9p_mounts.

    Includes pipe_name, python_version, python_exe (version is verified in guest,
    not installed).
    """
    all_rules = getattr(process_config, "all_rules", None)
    guest_working_dir = getattr(process_config, "guest_working_dir", None)
    if isinstance(guest_working_dir, str) and guest_working_dir.strip():
        # Match host cwd (e.g. repo root) so relative paths like tmp/file align with expose-rw=./tmp
        guest_cwd = guest_working_dir.strip()
    else:
        root_path = getattr(all_rules, "root_path", None)
        if isinstance(root_path, Path):
            # Fallback: config file directory (differs from host cwd when config is under a subdir)
            guest_cwd = str(root_path.parent.resolve()) if root_path.is_file() else str(root_path.resolve())
        else:
            guest_cwd = None
    cwd_for_ignore = guest_cwd if guest_cwd else str(Path.cwd().resolve())
    ignore_overlay_paths: list[str] = []
    if all_rules is not None:
        ignore_overlay_paths = qemu_ignore_overlay_abs_paths(all_rules, cwd_for_ignore)
    bootstrap_verbose = _qemu_show_boot_console_truthy(all_rules)
    script_content = _bootstrap_script_content(
        mounts,
        pipe_run_guest_path,
        python_version,
        python_exe,
        config_guest_path,
        guest_cwd=guest_cwd,
        bootstrap_verbose=bootstrap_verbose,
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
    (temp / IGNORE_OVERLAYS_FILE).write_text(
        "\n".join(ignore_overlay_paths) + ("\n" if ignore_overlay_paths else ""),
        encoding="utf-8",
    )
    debug_block = "debug:\n  verbosity: 2\n\n" if bootstrap_verbose else ""
    bootcmd_banner = (
        ("  - echo '[pysandbox] cloud-init bootcmd (early)' " "| tee /dev/ttyS0 /dev/console >/dev/null 2>&1 || true\n")
        if bootstrap_verbose
        else ""
    )
    runcmd_banner = (
        (
            "  - echo '[pysandbox] cloud-init runcmd (before bootstrap)' "
            "| tee /dev/ttyS0 /dev/console >/dev/null 2>&1 || true\n"
        )
        if bootstrap_verbose
        else ""
    )
    user_data = f"""#cloud-config
{debug_block}datasource_list: [NoCloud]
datasource:
  NoCloud:
    max_wait: 0

bootcmd:
{bootcmd_banner}  - sh -c 'echo 1 > /proc/sys/kernel/sysrq 2>/dev/null || true'
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
{runcmd_banner}  - systemctl stop serial-getty@ttyS0.service getty@ttyS0.service getty@tty1.service || true
  - systemctl mask serial-getty@ttyS0.service getty@ttyS0.service getty@tty1.service || true
  - rm -f /etc/resolv.conf && printf 'nameserver 10.0.2.3\\n' > /etc/resolv.conf
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
        f"{IGNORE_OVERLAYS_FILE}={IGNORE_OVERLAYS_FILE}",
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
    python_version: host Python major.minor (e.g. 3.13); guest must already have
        this version (verified, not installed).
    python_exe: host sys.executable path (9p-mounted in guest); used when
        available, else guest python is checked.
    config_guest_path: when set, guest reads config from this 9p path
        (e.g. /mnt/pysandbox_config/config.pkl) instead of pipe.
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
