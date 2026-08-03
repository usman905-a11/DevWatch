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
        full_path = os.path.join(self.root_dir, rel_path)
        if not os.path.exists(full_path):
            return ""
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    def get_codebase_context(self) -> Dict[str, str]:
        files = self.get_files()
        return {f: self.read_file(f) for f in files}
