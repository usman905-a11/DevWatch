import ast
import re
import hashlib
from typing import List, Optional
from pydantic import BaseModel, Field


class CodeChunk(BaseModel):
    chunk_id: str
    file_path: str
    start_line: int
    end_line: int
    symbol_name: Optional[str] = None
    content: str
    token_count: int

    @classmethod
    def create(
        cls,
        file_path: str,
        start_line: int,
        end_line: int,
        content: str,
        symbol_name: Optional[str] = None,
    ) -> "CodeChunk":
        norm_path = file_path.replace("\\", "/").strip("./")
        cleaned = re.sub(r"\s+", " ", content).strip().lower()
        chunk_hash = hashlib.sha256(f"{norm_path}:{start_line}:{end_line}:{cleaned}".encode("utf-8")).hexdigest()[:16]
        token_count = max(1, len(content) // 4)
        return cls(
            chunk_id=chunk_hash,
            file_path=norm_path,
            start_line=start_line,
            end_line=end_line,
            symbol_name=symbol_name,
            content=content,
            token_count=token_count,
        )


class SemanticCodeChunker:
    """Chunks source code cleanly along AST symbol (function/class) boundaries without truncating code logic."""

    def __init__(self, default_max_tokens: int = 1500):
        self.default_max_tokens = default_max_tokens

    def chunk_file(
        self, file_path: str, code_content: str, max_tokens: Optional[int] = None
    ) -> List[CodeChunk]:
        max_tok = max_tokens or self.default_max_tokens
        lines = code_content.splitlines()
        total_tokens = len(code_content) // 4

        if not lines or total_tokens <= max_tok:
            return [CodeChunk.create(file_path, 1, len(lines), code_content)]

        norm_path = file_path.replace("\\", "/").strip("./")

        if norm_path.endswith(".py"):
            try:
                tree = ast.parse(code_content)
                return self._chunk_python_ast(norm_path, lines, tree, max_tok)
            except Exception:
                pass

        return self._chunk_by_line_windows(norm_path, lines, max_tok)

    def _chunk_python_ast(
        self, file_path: str, lines: List[str], tree: ast.AST, max_tokens: int
    ) -> List[CodeChunk]:
        chunks: List[CodeChunk] = []

        # Identify top-level AST function and class nodes
        top_nodes = [
            node
            for node in ast.iter_child_nodes(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]

        if not top_nodes:
            return self._chunk_by_line_windows(file_path, lines, max_tokens)

        current_lines: List[str] = []
        current_start = 1
        current_name: Optional[str] = None
        last_end = 0

        for node in top_nodes:
            node_start = node.lineno
            node_end = getattr(node, "end_lineno", node_start)

            # Extract any preamble lines before node
            if node_start > last_end + 1 and not current_lines:
                current_start = last_end + 1

            node_snippet = "\n".join(lines[node_start - 1 : node_end])
            node_tokens = len(node_snippet) // 4

            if node_tokens > max_tokens:
                # Single node exceeds max_tokens -> flush current buffer first
                if current_lines:
                    text = "\n".join(current_lines)
                    chunks.append(CodeChunk.create(file_path, current_start, last_end, text, current_name))
                    current_lines = []
                # Chunk large single node by lines
                large_node_chunks = self._chunk_by_line_windows(
                    file_path, lines[node_start - 1 : node_end], max_tokens, start_offset=node_start, symbol=node.name
                )
                chunks.extend(large_node_chunks)
                last_end = node_end
                continue

            current_tokens = len("\n".join(current_lines)) // 4
            if current_tokens + node_tokens > max_tokens and current_lines:
                text = "\n".join(current_lines)
                chunks.append(CodeChunk.create(file_path, current_start, last_end, text, current_name))
                current_lines = []
                current_start = node_start
                current_name = node.name

            if not current_lines:
                current_start = node_start
                current_name = node.name

            current_lines.extend(lines[node_start - 1 : node_end])
            last_end = node_end

        if current_lines:
            text = "\n".join(current_lines)
            chunks.append(CodeChunk.create(file_path, current_start, last_end, text, current_name))

        return self.deduplicate_chunks(chunks)

    def _chunk_by_line_windows(
        self,
        file_path: str,
        lines: List[str],
        max_tokens: int,
        start_offset: int = 1,
        symbol: Optional[str] = None,
    ) -> List[CodeChunk]:
        chunks: List[CodeChunk] = []
        max_chars = max_tokens * 4
        overlap_lines = 5

        i = 0
        n = len(lines)

        while i < n:
            chunk_lines = []
            chunk_chars = 0
            start_line = start_offset + i

            while i < n and chunk_chars + len(lines[i]) + 1 <= max_chars:
                chunk_lines.append(lines[i])
                chunk_chars += len(lines[i]) + 1
                i += 1

            if not chunk_lines:
                chunk_lines.append(lines[i])
                i += 1

            end_line = start_offset + i - 1
            content = "\n".join(chunk_lines)
            chunks.append(CodeChunk.create(file_path, start_line, end_line, content, symbol))

            if i < n:
                i = max(i - overlap_lines, start_line - start_offset + 1)

        return self.deduplicate_chunks(chunks)

    def deduplicate_chunks(self, chunks: List[CodeChunk]) -> List[CodeChunk]:
        seen = set()
        unique = []
        for c in chunks:
            if c.chunk_id not in seen:
                seen.add(c.chunk_id)
                unique.append(c)
        return unique
