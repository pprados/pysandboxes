import yaml
import os
from pathlib import Path

def generate_flat_toml_configs(source_dir: str, destination_dir: str) -> None:
    """
    Parses Markdown files with YAML front matter.
    Replaces $ARGUMENTS with {{args}} in the body.
    Generates flat TOML files with only description and prompt fields.
    """
    src_path: Path = Path(source_dir)
    dest_path: Path = Path(destination_dir)

    if not src_path.exists() or not src_path.is_dir():
        print(f"[-] Error: Source directory '{source_dir}' not found.")
        return

    # Ensure destination directory exists on Ubuntu
    dest_path.mkdir(parents=True, exist_ok=True)

    print(f"--- Processing Markdown prompts from {src_path.absolute()} ---")

    count: int = 0
    for md_file in src_path.glob("*.md"):
        try:
            raw_content: str = md_file.read_text(encoding="utf-8")
            
            # Split YAML front matter from Markdown body
            parts: list[str] = raw_content.split("---", 2)
            
            if len(parts) < 3:
                print(f"[!] Skipping {md_file.name}: Missing YAML front matter.")
                continue

            # Parse metadata
            metadata: dict[str, str] | None = yaml.safe_load(parts[1])
            if not isinstance(metadata, dict):
                continue

            description: str = metadata.get("description", "")
            
            # Extract body and replace $ARGUMENTS with {{args}}
            markdown_body: str = parts[2].strip()
            markdown_body = markdown_body.replace("$ARGUMENTS", "{{args}}")

            output_file: Path = dest_path / f"{md_file.stem}.toml"

            # Manual TOML construction: flat keys and triple double-quotes
            toml_content: str = (
                f"description = \"{description}\"\n"
                "prompt = \"\"\"\n"
                f"{markdown_body}\n"
                "\"\"\"\n"
            )

            with open(output_file, "w", encoding="utf-8") as f:
                f.write(toml_content)
            
            print(f"[✓] Generated: {output_file.name}")
            count += 1
            
        except (IOError, yaml.YAMLError) as e:
            print(f"[!] Failed to process {md_file.name}: {e}")

    print(f"\n[+] Successfully generated {count} flat TOML file(s) in {destination_dir}.")

if __name__ == "__main__":
    # Settings for Philippe Prados environment
    SRC: str = "./.ia/commands"
    DEST: str = "./.gemini/commands"
    
    generate_flat_toml_configs(SRC, DEST)