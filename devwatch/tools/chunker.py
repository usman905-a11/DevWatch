import ast
from typing import List, Dict, Any


class CodeChunk:
    def __init__(self, name: str, chunk_type: str, start_line: int, end_line: int, code: str):
        self.name = name
        self.chunk_type = chunk_type  # "function", "class", "module_global"
        self.start_line = start_line
        self.end_line = end_line
        self.code = code


class ASTCodeChunker:
    """Chunks source code files into semantic blocks (classes, functions) using AST parsing."""

    def __init__(self, max_lines_per_chunk: int = 300):
        self.max_lines_per_chunk = max_lines_per_chunk

    def chunk_file(self, file_path: str, code_content: str) -> List[CodeChunk]:
        lines = code_content.splitlines()
        if len(lines) <= self.max_lines_per_chunk or not file_path.endswith(".py"):
            return [CodeChunk(name=file_path, chunk_type="full_file", start_line=1, end_line=len(lines), code=code_content)]

        chunks: List[CodeChunk] = []

        try:
            tree = ast.parse(code_content, filename=file_path)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    start = node.lineno
                    end = node.end_lineno if hasattr(node, "end_lineno") else len(lines)
                    chunk_code = "\n".join(lines[start - 1 : end])
                    chunk_type = "class" if isinstance(node, ast.ClassDef) else "function"
                    chunks.append(
                        CodeChunk(
                            name=node.name,
                            chunk_type=chunk_type,
                            start_line=start,
                            end_line=end,
                            code=chunk_code,
                        )
                    )

            if not chunks:
                # Fallback to sliding window if AST yielded no child class/function nodes
                for idx in range(0, len(lines), self.max_lines_per_chunk):
                    sub_lines = lines[idx : idx + self.max_lines_per_chunk]
                    chunks.append(
                        CodeChunk(
                            name=f"{file_path}_chunk_{idx//self.max_lines_per_chunk+1}",
                            chunk_type="sliding_window",
                            start_line=idx + 1,
                            end_line=idx + len(sub_lines),
                            code="\n".join(sub_lines),
                        )
                    )
        except Exception:
            # Fallback on syntax error
            for idx in range(0, len(lines), self.max_lines_per_chunk):
                sub_lines = lines[idx : idx + self.max_lines_per_chunk]
                chunks.append(
                    CodeChunk(
                        name=f"{file_path}_chunk_{idx//self.max_lines_per_chunk+1}",
                        chunk_type="fallback",
                        start_line=idx + 1,
                        end_line=idx + len(sub_lines),
                        code="\n".join(sub_lines),
                    )
                )

        return chunks
