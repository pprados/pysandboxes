#!/usr/bin/env python3
import subprocess
import sys

FENCE = "```"


def unwrap_output(output: str, output_file: str) -> str:
    # The CLI answers as in a chat: it may wrap the file in a code fence, and add a
    # comment after it, in the user's language. Strip a fence around the whole file;
    # refuse anything written after it rather than writing it into the file.
    lines = output.strip().split("\n")
    if lines[0].startswith(FENCE):
        if lines[-1].strip() != FENCE:
            raise RuntimeError(f"Claude CLI added text after its code fence, {output_file} left untouched")
        lines = lines[1:-1]
    return "\n".join(lines) + "\n"


def compress_template(template_file: str, output_file: str) -> None:
    with open(template_file) as f:
        content = f.read()

    prompt = (
        "Rewrite the Markdown file below in caveman ultra style, in English. Keep code blocks, commands, paths and "
        "identifiers unchanged. Output only the rewritten file: no surrounding code fence, no preamble, no comment "
        "about the changes, nothing written to disk. Never say that the file is generated, compressed or derived from "
        f"a template: no title, note or comment about how it was produced.\n\n{content}"
    )

    result = subprocess.run(
        [
            "claude",
            "--dangerously-skip-permissions",
            "--settings",
            '{"sandbox":{"enabled":true,"autoAllowBashIfSandboxed":true}}',
            "-p",
            prompt,
        ],
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed: {result.stderr}")

    if not result.stdout.strip():
        raise RuntimeError(f"Claude CLI returned empty output, {output_file} left untouched")

    text = unwrap_output(result.stdout, output_file)
    with open(output_file, "w") as f:
        f.write(text)

    print(f"Compressed: {template_file} → {output_file}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <template_file> <output_file>")
        sys.exit(1)

    compress_template(sys.argv[1], sys.argv[2])
