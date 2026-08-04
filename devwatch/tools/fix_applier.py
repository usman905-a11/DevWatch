import os
from devwatch.scanner import CodebaseScanner


def apply_code_fix(
    root_dir: str,
    file_path: str,
    line_number: int,
    target_snippet: str,
    replacement_code: str,
) -> bool:
    """Safely apply atomic code replacement to a target file within workspace root_dir."""
    scanner = CodebaseScanner(root_dir)
    safe_path = scanner._resolve_safe_path(file_path)

    if not os.path.exists(safe_path):
        raise FileNotFoundError(f"File not found: '{file_path}'")

    with open(safe_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.splitlines(keepends=True)

    # 1. Try exact line replacement if line_number is valid
    if 1 <= line_number <= len(lines):
        target_line = lines[line_number - 1]
        if target_snippet.strip() in target_line.strip() or not target_snippet.strip():
            # Preserve leading indentation if replacement doesn't include it
            indent = target_line[: len(target_line) - len(target_line.lstrip())]
            replacement_lines = [
                (indent + l if not l.startswith(indent) else l) + "\n"
                for l in replacement_code.splitlines()
            ]
            lines[line_number - 1 : line_number] = replacement_lines
            new_content = "".join(lines)
            with open(safe_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return True

    # 2. Try global target_snippet replacement if exact line mismatch
    if target_snippet and target_snippet in content:
        new_content = content.replace(target_snippet, replacement_code, 1)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True

    raise ValueError(f"Could not locate target snippet '{target_snippet}' at or near line {line_number} in {file_path}")
