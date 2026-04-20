#!/usr/bin/env python3
import subprocess
import sys

def compress_template(template_file: str, output_file: str) -> None:
    with open(template_file) as f:
        content = f.read()

    prompt = f"rewrite in caveman ultra:\n\n{content}"

    result = subprocess.run(
        ['claude', '--dangerously-skip-permissions',
         '--settings','{"sandbox":{"enabled":true,"autoAllowBashIfSandboxed":true}}',
         '-c', prompt],
        input=content,
        text=True,
        capture_output=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed: {result.stderr}")

    with open(output_file, 'w') as f:
        f.write(result.stdout)

    print(f"Compressed: {template_file} → {output_file}")

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <template_file> <output_file>")
        sys.exit(1)

    compress_template(sys.argv[1], sys.argv[2])
