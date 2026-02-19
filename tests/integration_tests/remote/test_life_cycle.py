# %% Process life cycle
import os
import random
import threading
import time
from pathlib import Path
from typing import List

from pysandboxes import sandboxes

from ..sample import config_path
from .test_rpc import sync_function


def find_process_childrens(parent_pid: int) -> List[int]:
    children_pids: List[int] = []

    try:
        # Iterate through all entries in the /proc filesystem.
        # Each directory named after a number represents a running process PID.
        for pid_dir in os.listdir("/proc"):
            # Check if the directory name is purely numeric (a PID)
            if pid_dir.isdigit():
                try:
                    current_pid = int(pid_dir)
                    status_file_path = Path(f"/proc/{pid_dir}/status")

                    # Ensure the status file exists and is readable.
                    # A process might exit between listdir and open,
                    # or permissions might be restricted.
                    if status_file_path.exists() and os.access(
                        status_file_path, os.R_OK
                    ):
                        with open(status_file_path, "r") as f:
                            # Read lines until 'PPid:' is found
                            for line in f:
                                if line.startswith("PPid:"):
                                    # Extract the parent PID (PPid) from the line
                                    ppid_str = line.split(":")[1].strip()
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
        return []
    return children_pids


def _worker(thread_id: int) -> None:
    """
    A function that simulates some work and modifies a shared resource.
    The intention is to create a race condition.
    """
    # Simulate some processing time
    processing_time: float = random.uniform(0.01, 0.05)
    time.sleep(processing_time)
    for i in range(10):
        result_sync = sync_function("a", b=thread_id)
        assert result_sync == f"a {thread_id}"


def test_multi_thread() -> None:
    """
    Check if the multiple call at the same time are not shuffled
    """
    with sandboxes(config_path=config_path):
        r = range(5)
        threads: List[threading.Thread] = []

        for i in r:
            # Create a new thread with the worker function and a unique ID
            thread: threading.Thread = threading.Thread(
                target=_worker, args=(i,), name=f"Thread-{i}"
            )
            threads.append(thread)

            # Start the thread
            thread.start()

        # Wait for all threads to complete their execution
        for thread in threads:
            thread.join()
