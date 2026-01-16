# TODO: c'est quoi ?
import os
import subprocess
import sys
import time

from pysandboxes.remote import daemon

def main():
    subprocess.run(
        [
            sys.executable,
            '-m',
            daemon.__name__,
            "--outer-sandbox", "subprocess"
        ],
        capture_output=True,  # Capture stdout and stderr
        text=True,
        check=True,
    )

if __name__ == "__main__":
    main()