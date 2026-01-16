# %% Process life cycle
import os
import signal
import sys
import time
from pathlib import Path
from typing import List

import _pytest
import pytest


def test_kill_child_process(capsys: _pytest.capture.CaptureFixture):
    """
    Check if the child is killed when the parent is killed
    """
    # FIXME: ne semble pas fonctionner si j'ajoute un os-firewall
    if os.name != 'posix':
        pytest.skip("This test is only for POSIX systems")

    def find_children(parent_pid: int) -> List[int]:
        children_pids: List[int] = []

        try:
            # Iterate through all entries in the /proc filesystem.
            # Each directory named after a number represents a running process PID.
            for pid_dir in os.listdir('/proc'):
                # Check if the directory name is purely numeric (a PID)
                if pid_dir.isdigit():
                    try:
                        current_pid = int(pid_dir)
                        status_file_path = Path(f'/proc/{pid_dir}/status')

                        # Ensure the status file exists and is readable.
                        # A process might exit between listdir and open, or permissions might be restricted.
                        if status_file_path.exists() and os.access(
                                status_file_path, os.R_OK):
                            with open(status_file_path, 'r') as f:
                                # Read lines until 'PPid:' is found
                                for line in f:
                                    if line.startswith('PPid:'):
                                        # Extract the parent PID (PPid) from the line
                                        ppid_str = line.split(':')[1].strip()
                                        if ppid_str.isdigit():
                                            ppid = int(ppid_str)
                                            if ppid == parent_pid:
                                                children_pids.append(current_pid)
                                        # No need to read further lines in this status file
                                        break
                    except (ValueError, FileNotFoundError, PermissionError):
                        # These exceptions can occur if:
                        # - The PID directory suddenly disappears (process exited).
                        # - The status file cannot be opened due to permissions.
                        # - The PPid string is not a valid integer.
                        # We simply skip this process and continue.
                        continue
        except FileNotFoundError:
            pytest.skip(
                "Error: /proc directory not found. This function requires a Linux-like system.")
        return children_pids

    from . import launch_child
    import subprocess
    child = subprocess.Popen(
        [
            sys.executable,
            '-m',
            launch_child.__name__,
        ],
    )
    time.sleep(0.5)
    childs_pid = find_children(child.pid)
    assert len(childs_pid) == 1, "Child process not found"
    child_pid = childs_pid[0]
    assert Path(f"/proc/{child_pid}").exists(), "Child process not found"
    os.kill(child.pid, signal.SIGKILL)
    child.wait()
    assert not Path(f"/proc/{child_pid}").exists(), "Child process alive"


@pytest.mark.skip(reason="Not working")
def test_kill_parent_process():
    raise NotImplementedError


@pytest.mark.skip(reason="Not working")
def test_multi_thread():
    """
    Check if the multiple call at the same time are not shuffled
    """
    raise NotImplementedError
