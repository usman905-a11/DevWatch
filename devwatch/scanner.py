import os
import fnmatch
from pathlib import Path
from typing import List, Dict, Set
from urllib.parse import unquote

from devwatch.config import Config

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


IGNORED_PATTERNS = {
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "*.pyc",
    "*.pyo",
    "*.so",
    "*.dll",
    "*.exe",
}


class CodebaseScanner:
    """Scans repository files and extracts source code context within a strict security sandbox."""

    def __init__(self, root_dir: str):
        # Unquote URL-encoded paths if present
        unquoted_root = unquote(str(root_dir))
        if "\x00" in unquoted_root:
            raise ValueError("Invalid workspace root: Null bytes not allowed")

        requested_path = Path(unquoted_root)
        
        # Check if a server workspace base directory is explicitly restricted via env var or custom Config
        env_workspace_dir = os.getenv("DEVWATCH_WORKSPACE_DIR")
        is_customized_config = (Config.WORKSPACE_BASE_DIR != os.getcwd())

        if env_workspace_dir or is_customized_config:
            base_path = env_workspace_dir if env_workspace_dir else Config.WORKSPACE_BASE_DIR
            workspace_base = Path(base_path).resolve()

            if not requested_path.is_absolute():
                candidate_root = (workspace_base / requested_path).resolve()
            else:
                candidate_root = requested_path.resolve()

            try:
                if candidate_root != workspace_base and not candidate_root.is_relative_to(workspace_base):
                    raise ValueError("Access denied: Target workspace is outside server authorized workspace base directory")
            except AttributeError:
                try:
                    if candidate_root != workspace_base:
                        candidate_root.relative_to(workspace_base)
                except ValueError:
                    raise ValueError("Access denied: Target workspace is outside server authorized workspace base directory")
        else:
            candidate_root = requested_path.resolve()

        if not candidate_root.exists() or not candidate_root.is_dir():
            raise ValueError("Invalid workspace root: Directory does not exist")

        self.root_dir = candidate_root
        self.custom_ignores = self._load_custom_ignores()

    def _load_custom_ignores(self) -> Set[str]:
        patterns = set()
        for ignore_file_name in (".gitignore", ".devwatchignore"):
            ig_path = self.root_dir / ignore_file_name
            if ig_path.exists() and ig_path.is_file():
                try:
                    for line in ig_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            patterns.add(line)
                except Exception:
                    pass
        return patterns

    def is_blocked_file(self, file_path: Path) -> bool:
        """Check if file_path matches any blocked sensitive filenames or patterns."""
        name = file_path.name.lower()
        if name in Config.BLOCKED_FILENAMES:
            return True
        for pattern in Config.BLOCKED_PATTERNS:
            if fnmatch.fnmatch(name, pattern):
                return True
        for custom in self.custom_ignores:
            if fnmatch.fnmatch(name, custom) or fnmatch.fnmatch(file_path.name, custom):
                return True
        return False

    def is_ignored_file(self, file_path: Path) -> bool:
        """Check if file matches build artifacts, minified, or lock file ignore patterns."""
        name = file_path.name.lower()
        if self.is_blocked_file(file_path):
            return True
        for pattern in IGNORED_PATTERNS:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False

    def _resolve_safe_path(self, rel_path: str) -> Path:
        """Resolve rel_path relative to root_dir using Path.resolve() and verify sandbox boundaries."""
        if "\x00" in rel_path:
            raise ValueError("Invalid path: Null bytes not allowed")

        unquoted_rel = unquote(rel_path)
        if "\x00" in unquoted_rel:
            raise ValueError("Invalid path: Null bytes not allowed")

        target_path = (self.root_dir / unquoted_rel).resolve()

        # Verify resolved path is strictly a descendant of self.root_dir (handles symlinks, .., etc.)
        try:
            if not target_path.is_relative_to(self.root_dir):
                raise ValueError(f"Path traversal attempt blocked: '{rel_path}' is outside workspace sandbox")
        except AttributeError:
            try:
                target_path.relative_to(self.root_dir)
            except ValueError:
                raise ValueError(f"Path traversal attempt blocked: '{rel_path}' is outside workspace sandbox")

        if self.is_blocked_file(target_path):
            raise ValueError(f"Access denied: '{rel_path}' is a blocked sensitive file")

        return target_path

    def get_files(self) -> List[str]:
        relative_files = []
        total_size = 0
        max_files = min(Config.MAX_FILES_PER_REVIEW, Config.MAX_FILE_COUNT)
        max_repo_bytes = min(Config.MAX_REPO_TOTAL_BYTES, Config.MAX_REPO_SIZE_BYTES)
        
        for root, dirs, files in os.walk(self.root_dir):
            # Enforce max directory depth
            rel_root = os.path.relpath(root, self.root_dir)
            depth = 0 if rel_root == "." else len(Path(rel_root).parts)
            if depth > Config.MAX_DIRECTORY_DEPTH:
                dirs[:] = []
                continue

            # Prune ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]

            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in ALLOWED_EXTENSIONS:
                    file_path = Path(root) / file
                    if self.is_ignored_file(file_path):
                        continue


                    try:
                        file_stat = file_path.stat()
                        if file_stat.st_size > Config.MAX_BYTES_PER_FILE:
                            continue
                        if total_size + file_stat.st_size > max_repo_bytes:
                            break
                        total_size += file_stat.st_size
                    except Exception:
                        continue

                    rel_path = os.path.relpath(file_path, self.root_dir).replace("\\", "/")
                    relative_files.append(rel_path)

                    if len(relative_files) >= max_files:
                        return sorted(relative_files)

        return sorted(relative_files)

    def read_file(self, rel_path: str) -> str:
        safe_path = self._resolve_safe_path(rel_path)
        if not safe_path.exists() or safe_path.is_dir():
            return ""

        ext = safe_path.suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Access denied: File extension '{ext}' is not permitted")

        file_stat = safe_path.stat()
        if file_stat.st_size > Config.MAX_FILE_SIZE_BYTES:
            raise ValueError(f"File size ({file_stat.st_size} bytes) exceeds maximum limit of {Config.MAX_FILE_SIZE_BYTES} bytes")

        with open(safe_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    def get_codebase_context(self) -> Dict[str, str]:
        files = self.get_files()
        return {f: self.read_file(f) for f in files}

    def write_file(self, rel_path: str, content: str) -> bool:
        safe_path = self._resolve_safe_path(rel_path)
        
        ext = safe_path.suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Access denied: File extension '{ext}' is not permitted")

        if len(content.encode("utf-8")) > Config.MAX_FILE_SIZE_BYTES:
            raise ValueError(f"Content size exceeds maximum file limit of {Config.MAX_FILE_SIZE_BYTES} bytes")

        os.makedirs(safe_path.parent, exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True

    def get_tree_structure(self) -> List[Dict]:
        """Returns recursive nested tree nodes for IDE file explorer components."""
        def build_node(dir_path: Path, current_depth: int = 0) -> List[Dict]:
            if current_depth > Config.MAX_DIRECTORY_DEPTH:
                return []

            items = []
            try:
                entries = sorted(os.listdir(dir_path))
            except Exception:
                return items

            for entry in entries:
                if entry in IGNORED_DIRS or entry.startswith("."):
                    continue
                full_path = dir_path / entry
                if self.is_blocked_file(full_path):
                    continue

                rel_path = os.path.relpath(full_path, self.root_dir).replace("\\", "/")

                if full_path.is_dir():
                    children = build_node(full_path, current_depth + 1)
                    if children:
                        items.append(
                            {
                                "name": entry,
                                "path": rel_path,
                                "type": "directory",
                                "children": children,
                            }
                        )
                else:
                    ext = full_path.suffix.lower()
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
