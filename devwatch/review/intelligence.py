"""Bounded deterministic language facts; no source execution or model summaries."""
import ast
from pathlib import Path, PurePosixPath
import json
import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version

def _parser_version():
    values = ["intelligence-v2", ".".join(map(str, sys.version_info[:3]))]
    for package in ("tree-sitter", "tree-sitter-javascript", "tree-sitter-typescript"):
        try:
            values.append(package + "=" + version(package))
        except PackageNotFoundError:
            values.append(package + "=unavailable")
    return ":".join(values)


PARSER_VERSION = _parser_version()
MAX_NODES = 100_000


def analyze_source(path: str, source: str):
    if len(source.encode("utf-8")) > 500_000:
        raise ValueError("Source exceeds parser input bound")
    request = json.dumps({"path": path, "source": source}, ensure_ascii=False).encode("utf-8")
    environment = {key: value for key, value in os.environ.items() if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
    try:
        result = subprocess.run([sys.executable, "-I", str(Path(__file__).with_name("intelligence_worker.py"))],
            input=request, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment, timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode != 0 or len(result.stdout) > 2_000_000:
            raise ValueError("Parser worker failed or exceeded output bounds")
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        return {"status": "parse_failed", "symbols": [], "imports": [], "calls": [], "branch_count": 0,
                "limitations": ["Parser failed or exceeded its process/time/output bound"]}


def _analyze_source(path: str, source: str):
    facts = {"status": "parser_unavailable", "symbols": [], "imports": [], "calls": [],
             "branch_count": 0, "limitations": ["AST parser unavailable for this language"]}
    extension = PurePosixPath(path).suffix.lower()
    try:
        if extension == ".py":
            tree = ast.parse(source)
            stack = [(tree, "<module>")]
            count = 0
            while stack:
                node, caller = stack.pop()
                count += 1
                if count > MAX_NODES:
                    raise ValueError("AST node bound exceeded")
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    facts["symbols"].append({"name": node.name, "start_line": node.lineno, "end_line": node.end_lineno})
                    caller = node.name
                if isinstance(node, ast.Import):
                    facts["imports"].extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    facts["imports"].append("." * node.level + (node.module or ""))
                if isinstance(node, ast.Call):
                    target = ast.unparse(node.func) if isinstance(node.func, (ast.Name, ast.Attribute)) else "<dynamic>"
                    facts["calls"].append({"target": target[:256], "line": node.lineno, "caller": caller})
                facts["branch_count"] += isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.IfExp, ast.Match, ast.BoolOp))
                stack.extend((child, caller) for child in reversed(list(ast.iter_child_nodes(node))))
        elif extension in {".js", ".jsx", ".ts", ".tsx"}:
            from tree_sitter import Language, Parser
            import tree_sitter_javascript as javascript
            import tree_sitter_typescript as typescript
            grammar = (typescript.language_tsx() if extension == ".tsx" else typescript.language_typescript()
                       if extension == ".ts" else javascript.language())
            parser = Parser(Language(grammar))
            # Byte input avoids unstable native callback parsing. The parent
            # bounds the complete process, including malformed-source failures.
            tree = parser.parse(source.encode("utf-8"))
            if tree is None or tree.root_node.has_error:
                raise ValueError("Source could not be parsed")
            stack, count = [(tree.root_node, "<module>")], 0
            while stack:
                node, caller = stack.pop()
                count += 1
                if count > MAX_NODES:
                    raise ValueError("AST node bound exceeded")
                value = node.child_by_field_name("value")
                symbol = node.type in {"function_declaration", "class_declaration", "method_definition", "interface_declaration", "type_alias_declaration"}
                symbol |= node.type == "variable_declarator" and value is not None and value.type in {"arrow_function", "function_expression"}
                if symbol:
                    name = node.child_by_field_name("name")
                    if name is not None:
                        caller = name.text.decode("utf-8")
                        facts["symbols"].append({"name": caller, "start_line": node.start_point.row + 1,
                                                 "end_line": node.end_point.row + 1})
                if node.type == "import_statement":
                    name = node.child_by_field_name("source")
                    if name is not None:
                        facts["imports"].append(name.text.decode("utf-8")[1:-1])
                if node.type == "call_expression":
                    target = node.child_by_field_name("function")
                    text = target.text.decode("utf-8") if target is not None and target.type in {"identifier", "member_expression"} else "<dynamic>"
                    facts["calls"].append({"target": text[:256], "line": node.start_point.row + 1, "caller": caller})
                facts["branch_count"] += node.type in {"if_statement", "for_statement", "while_statement", "switch_case", "catch_clause", "ternary_expression"}
                stack.extend((child, caller) for child in reversed(node.named_children))
        else:
            return facts
    except ImportError:
        return facts
    except (SyntaxError, RecursionError, ValueError):
        return {**facts, "status": "parse_failed", "symbols": [], "imports": [], "calls": [],
                "limitations": ["Source could not be parsed within AST limits"]}
    facts.update(status="parsed", imports=sorted(set(facts["imports"])),
                 limitations=["Call targets are syntactic; dynamic dispatch is unresolved"])
    facts["symbols"] = sorted(facts["symbols"], key=lambda item: (item["start_line"], item["name"]))[:2000]
    facts["calls"] = sorted(facts["calls"], key=lambda item: item["line"])[:5000]
    return facts


def import_edges(facts, scope):
    scope = set(scope)
    edges, unresolved = [], []
    for path in sorted(scope):
        for name in facts[path]["imports"]:
            if path.endswith(".py"):
                relative = len(name) - len(name.lstrip("."))
                base = PurePosixPath(path).parent
                for _ in range(max(0, relative - 1)):
                    base = base.parent
                module = name.lstrip(".").replace(".", "/")
                stem = str(base / module) if relative else module
                candidates = [stem + ".py", stem + "/__init__.py"]
            elif name.startswith("."):
                parts = list(PurePosixPath(path).parent.parts)
                for part in name.split("/"):
                    if part == "..":
                        if parts:
                            parts.pop()
                    elif part not in {"", "."}:
                        parts.append(part)
                stem = "/".join(parts)
                candidates = [stem] + [stem + suffix for suffix in (".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js")]
            else:
                candidates = []
            found = next((candidate for candidate in candidates if candidate in scope), None)
            if found:
                edges.append({"from": path, "to": found, "import": name})
            else:
                unresolved.append({"from": path, "import": name})
    return {"edges": edges, "unresolved": unresolved, "limitations": ["Dependencies outside assigned captured scope remain unresolved"]}
