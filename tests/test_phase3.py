import os
import pytest
from devwatch.tools.static_analyzer import ASTStaticAnalyzerTool
from devwatch.tools.chunker import ASTCodeChunker
from devwatch.tools.dependency_map import DependencyMapper


def test_ast_static_analyzer_detection():
    analyzer = ASTStaticAnalyzerTool()
    sample_code = """
import os

AWS_SECRET_ACCESS_KEY = "AKIA1234567890ABCDEF1234"

def unsafe_exec(user_input):
    query = f"SELECT * FROM users WHERE name='{user_input}'"
    eval(user_input)
    os.system("ping " + user_input)
    try:
        do_something()
    except:
        pass
"""
    issues = analyzer.analyze_file("sample.py", sample_code)
    titles = [i.title for i in issues]
    assert any("Secret" in t for t in titles)
    assert any("SQL" in t for t in titles)
    assert any("Dynamic Code Execution" in t for t in titles)
    assert any("OS Command Injection" in t for t in titles)
    assert any("Bare Except" in t for t in titles)


def test_ast_code_chunker_classes_functions():
    chunker = ASTCodeChunker(max_lines_per_chunk=5)
    sample_code = """class UserHandler:
    def __init__(self):
        self.name = "admin"

    def process(self):
        return True

def standalone_helper(x, y):
    return x + y
"""
    chunks = chunker.chunk_file("sample.py", sample_code)
    assert len(chunks) >= 2
    chunk_names = [c.name for c in chunks]
    assert "UserHandler" in chunk_names or "standalone_helper" in chunk_names


def test_dependency_mapper_imports():
    mapper = DependencyMapper(root_dir=os.path.dirname(os.path.abspath(__file__)))
    sample_code = """import os
import sys
from devwatch.models import ReviewReport
from devwatch.scanner import CodebaseScanner
"""
    deps = mapper.get_file_dependencies("test_file.py", sample_code)
    assert "os" in deps["external_imports"]
    assert "sys" in deps["external_imports"]
    assert any("devwatch" in d for d in deps["internal_imports"] + deps["external_imports"])
