import os
import re
from concurrent.futures import ThreadPoolExecutor
import posixpath
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

from devwatch.config import Config
from devwatch.review.models import ChangedRegion
from devwatch.scanner import ALLOWED_EXTENSIONS
from devwatch.tools.dependency_map import DependencyMapper


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_SCRIPT_IMPORT_RE = re.compile(
    r"\b(?:from\s+|import\s*(?:\(\s*)?|require\s*\(\s*)['\"](\.[^'\"]+)['\"]"
)
_SCRIPT_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")


class GitChangeCollector:
    """Collect changed source ranges without invoking a shell."""

    def collect(self, root_path: str | Path) -> List[ChangedRegion]:
        root = Path(root_path).resolve()
        self._run(root, "rev-parse", "--is-inside-work-tree")

        ranges: Dict[str, List[Tuple[int, int]]] = {}
        # Compare HEAD with the working tree so staged line numbers include
        # any later unstaged insertions before them.
        if self._has_head(root):
            diffs = [("diff", "HEAD", "--unified=0", "--no-ext-diff", "--relative")]
        else:
            diffs = [
                ("diff", "--unified=0", "--no-ext-diff", "--relative"),
                ("diff", "--cached", "--unified=0", "--no-ext-diff", "--relative"),
            ]
        for args in diffs:
            self._parse_diff(root, self._run(root, *args), ranges)

        untracked = self._run(
            root, "ls-files", "--others", "--exclude-standard", "-z"
        )
        untracked_files = []
        for rel_path in filter(None, untracked.split("\0")):
            normalized = rel_path.replace("\\", "/")
            candidate = root / normalized
            if candidate.is_symlink():
                continue
            path = candidate.resolve()
            if not path.is_relative_to(root):
                continue
            if path.suffix.lower() in ALLOWED_EXTENSIONS and path.is_file():
                untracked_files.append((normalized, path))
        if untracked_files:
            worker_count = min(32, max(4, (os.cpu_count() or 4) + 4))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                line_counts = executor.map(
                    lambda item: max(
                        1, len(item[1].read_text(encoding="utf-8", errors="ignore").splitlines())
                    ),
                    untracked_files,
                )
                for (normalized, _), line_count in zip(untracked_files, line_counts):
                    ranges[normalized] = [(1, line_count)]

        return [
            ChangedRegion(file_path=path, start_line=start, end_line=end)
            for path, spans in sorted(ranges.items())
            if (root / path).is_file()
            for start, end in sorted(set(spans))
        ]

    def _parse_diff(
        self, root: Path, diff_text: str, ranges: Dict[str, List[Tuple[int, int]]]
    ) -> None:
        current_file = ""
        for line in diff_text.splitlines():
            if line.startswith("diff --git ") or line == "+++ /dev/null":
                current_file = ""
                continue
            if line.startswith("+++ b/"):
                current_file = line[6:].replace("\\", "/")
                continue
            match = _HUNK_RE.match(line)
            if not match or not current_file:
                continue
            path = (root / current_file).resolve()
            if path.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            start = max(1, int(match.group(1)))
            count = int(match.group(2) or "1")
            end = start if count == 0 else start + count - 1
            ranges.setdefault(current_file, []).append((start, end))

    @staticmethod
    def _has_head(root: Path) -> bool:
        return subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=root,
            capture_output=True,
            timeout=15,
        ).returncode == 0

    @staticmethod
    def _run(root: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-c", "core.quotePath=false", *args],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if result.returncode != 0:
            raise ValueError(result.stderr.strip() or "target path is not a Git repository")
        return result.stdout


class ContextSelector:
    """Select immediate dependency and test context without expanding review targets."""

    def __init__(self, root_path: str | Path):
        self.root = Path(root_path).resolve()
        self.mapper = DependencyMapper(str(self.root))

    def select(self, changed_files: List[str], available_files: List[str]) -> List[str]:
        available = set(available_files)
        changed_set = set(changed_files)
        if available.issubset(changed_set):
            return []
        by_name: Dict[str, List[str]] = {}
        for candidate in available_files:
            by_name.setdefault(Path(candidate).name.lower(), []).append(candidate)
        selected = set()
        for changed in changed_files:
            path = self.root / changed
            if path.suffix.lower() == ".py" and path.is_file():
                code = path.read_text(encoding="utf-8", errors="ignore")
                dependencies = self.mapper.get_file_dependencies(changed, code)
                for imported in dependencies["internal_imports"]:
                    module = imported.split(" ", 1)[0]
                    module_path = module.replace(".", "/")
                    for candidate in (f"{module_path}.py", f"{module_path}/__init__.py"):
                        if candidate in available and candidate not in changed_set:
                            selected.add(candidate)
            elif path.suffix.lower() in _SCRIPT_EXTENSIONS and path.is_file():
                code = path.read_text(encoding="utf-8", errors="ignore")
                selected.update(self._script_imports(changed, code, available) - changed_set)

            stem = path.stem.lower()
            expected_names = {
                f"test_{stem}.py",
                f"{stem}_test.py",
                f"{stem}.test.ts",
                f"{stem}.test.tsx",
                f"{stem}.spec.ts",
                f"{stem}.spec.tsx",
            }
            for expected_name in expected_names:
                for candidate in by_name.get(expected_name, []):
                    if candidate not in changed_set:
                        selected.add(candidate)

        changed_modules = {
            path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
            for path in changed_files
            if path.endswith(".py")
        }
        for candidate in available_files:
            if candidate in changed_set:
                continue
            path = self.root / candidate
            if not path.is_file():
                continue
            if path.suffix.lower() == ".py":
                code = path.read_text(encoding="utf-8", errors="ignore")
                imports = self.mapper.get_file_dependencies(candidate, code)["internal_imports"]
                if any(imported.split(" ", 1)[0] in changed_modules for imported in imports):
                    selected.add(candidate)
            elif path.suffix.lower() in _SCRIPT_EXTENSIONS:
                code = path.read_text(encoding="utf-8", errors="ignore")
                if self._script_imports(candidate, code, available) & changed_set:
                    selected.add(candidate)

        limit = max(0, Config.MAX_FILES_PER_REVIEW - len(changed_set))
        return sorted(selected)[:limit]

    @staticmethod
    def _script_imports(file_path: str, code: str, available: set[str]) -> set[str]:
        directory = posixpath.dirname(file_path)
        imports = set()
        for module in _SCRIPT_IMPORT_RE.findall(code):
            base = posixpath.normpath(posixpath.join(directory, module))
            for candidate in (
                base,
                *(base + ext for ext in _SCRIPT_EXTENSIONS),
                *(f"{base}/index{ext}" for ext in _SCRIPT_EXTENSIONS),
            ):
                if candidate in available:
                    imports.add(candidate)
        return imports
