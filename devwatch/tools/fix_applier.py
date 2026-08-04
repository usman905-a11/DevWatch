import os
from devwatch.scanner import CodebaseScanner


def apply_code_fix(
    root_dir: str,
    file_path: str,
    line_number: int,
    target_snippet: str,
    replacement_code: str,
) -> bool:
    """Safely apply atomic line-targeted code replacement within authorized workspace sandbox."""
    scanner = CodebaseScanner(root_dir)
    safe_path = scanner._resolve_safe_path(file_path)

    if not safe_path.exists() or safe_path.is_dir():
        raise FileNotFoundError(f"File not found: '{file_path}'")

    content = scanner.read_file(file_path)
    lines = content.splitlines(keepends=True)

    # Validate target line number range
    if not (1 <= line_number <= len(lines)):
        raise ValueError(f"Line number {line_number} is out of range for '{file_path}' (total lines: {len(lines)})")

    target_line = lines[line_number - 1]
    
    # Target snippet must match target line if provided
    if target_snippet.strip() and target_snippet.strip() not in target_line.strip():
        raise ValueError(f"Target snippet does not match code at line {line_number} in '{file_path}'")

    # Preserve leading indentation if replacement doesn't specify its own
    indent = target_line[: len(target_line) - len(target_line.lstrip())]
    replacement_lines = [
        (indent + l if not l.startswith(indent) else l) + "\n"
        for l in replacement_code.splitlines()
    ]
    
    lines[line_number - 1 : line_number] = replacement_lines
    new_content = "".join(lines)
    
    return scanner.write_file(file_path, new_content)
