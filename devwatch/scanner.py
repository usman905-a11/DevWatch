import os
from typing import List, Dict

IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".idea",
    ".vscode",
    "dist",
    "build",
    ".next",
    "coverage",
}

ALLOWED_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".go",
    ".rs",
    ".c",
    ".cpp",
    ".h",
    ".html",
    ".css",
    ".md",
    ".json",
    ".yaml",
    ".yml",
}


class CodebaseScanner:
    """Scans repository files and extracts source code context while ignoring binary/build artifacts."""

    def __init__(self, root_dir: str):
        self.root_dir = os.path.abspath(root_dir)

    def _resolve_safe_path(self, rel_path: str) -> str:
        """Resolve rel_path relative to root_dir and verify it remains strictly within root_dir."""
        full_path = os.path.abspath(os.path.join(self.root_dir, rel_path))
        real_root = os.path.realpath(self.root_dir)
        real_full = os.path.realpath(full_path)
        try:
            if os.path.commonpath([real_root, real_full]) != real_root:
                raise ValueError(f"Path traversal attempt blocked: '{rel_path}' is outside root '{self.root_dir}'")
        except ValueError as err:
            raise ValueError(f"Path traversal attempt blocked: '{rel_path}' is outside root '{self.root_dir}'") from err
        return real_full

    def get_files(self) -> List[str]:
        relative_files = []
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in ALLOWED_EXTENSIONS:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, self.root_dir).replace("\\", "/")
                    relative_files.append(rel_path)
        return sorted(relative_files)

    def read_file(self, rel_path: str) -> str:
        full_path = self._resolve_safe_path(rel_path)
        if not os.path.exists(full_path) or os.path.isdir(full_path):
            return ""
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    def get_codebase_context(self) -> Dict[str, str]:
        files = self.get_files()
        return {f: self.read_file(f) for f in files}

    def write_file(self, rel_path: str, content: str) -> bool:
        full_path = self._resolve_safe_path(rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True

    def get_tree_structure(self) -> List[Dict]:

        """Returns recursive nested tree nodes for IDE file explorer components."""
        def build_node(dir_path: str) -> List[Dict]:
            items = []
            try:
                entries = sorted(os.listdir(dir_path))
            except Exception:
                return items

            for entry in entries:
                if entry in IGNORED_DIRS:
                    continue
                full_path = os.path.join(dir_path, entry)
                rel_path = os.path.relpath(full_path, self.root_dir).replace("\\", "/")

                if os.path.isdir(full_path):
                    children = build_node(full_path)
                    if children:  # Only show non-empty directories
                        items.append(
                            {
                                "name": entry,
                                "path": rel_path,
                                "type": "directory",
                                "children": children,
                            }
                        )
                else:
                    ext = os.path.splitext(entry)[1].lower()
                    if ext in ALLOWED_EXTENSIONS:
                        items.append(
                            {
                                "name": entry,
                                "path": rel_path,
                                "type": "file",
                            }
                        )
            return items

        return build_node(self.root_dir)

