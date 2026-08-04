import os
import ast
from typing import Dict, List, Set


class DependencyMapper:
    """Parses import dependencies across a codebase to provide caller/callee cross-file context."""

    def __init__(self, root_dir: str):
        self.root_dir = os.path.abspath(root_dir)

    def get_file_dependencies(self, rel_path: str, code_content: str) -> Dict[str, List[str]]:
        """Parse imports from code_content and map them to relative file paths or module names in the repo."""
        dependencies: Dict[str, List[str]] = {
            "internal_imports": [],
            "external_imports": [],
        }

        if not code_content or not rel_path.endswith(".py"):
            return dependencies

        try:
            tree = ast.parse(code_content, filename=rel_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        mod_name = alias.name
                        if self._is_internal_module(mod_name):
                            dependencies["internal_imports"].append(mod_name)
                        else:
                            dependencies["external_imports"].append(mod_name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        mod_name = node.module
                        imported_symbols = [alias.name for alias in node.names]
                        symbols_str = f"{mod_name} ({', '.join(imported_symbols)})"
                        if self._is_internal_module(mod_name):
                            dependencies["internal_imports"].append(symbols_str)
                        else:
                            dependencies["external_imports"].append(symbols_str)
        except Exception:
            pass

        # Deduplicate
        dependencies["internal_imports"] = sorted(list(set(dependencies["internal_imports"])))
        dependencies["external_imports"] = sorted(list(set(dependencies["external_imports"])))
        return dependencies

    def _is_internal_module(self, module_name: str) -> bool:
        """Check if module_name maps to a local directory or python file within root_dir."""
        parts = module_name.split(".")
        candidate_path = os.path.join(self.root_dir, *parts)
        if os.path.exists(f"{candidate_path}.py") or os.path.isdir(candidate_path):
            return True
        # Check relative to top-level packages
        top_package = parts[0]
        if os.path.exists(os.path.join(self.root_dir, top_package)):
            return True
        return False
