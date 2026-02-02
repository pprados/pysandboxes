# fake main to test the pdeathsig
import subprocess
import sys


def main():
    from pysandboxes.remote import run_daemon

    subprocess.run(
        [
            sys.executable,
            '-m',
            run_daemon.__name__,
        ],
        capture_output=True,  # Capture stdout and stderr
        text=True,
        check=True,
    )

if __name__ == "__main__":
    main()