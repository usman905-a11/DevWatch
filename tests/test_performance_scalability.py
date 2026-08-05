import pytest
from devwatch.config import Config
from devwatch.scanner import CodebaseScanner
from devwatch.chunker import SemanticCodeChunker, CodeChunk
from devwatch.cache import IsolatedResponseCache
from devwatch.pipeline.context import ReviewContext
from devwatch.pipeline.dag import ReviewPipeline


def test_large_file_ast_symbol_chunking():
    # Build large Python source with 5 distinct functions
    funcs = []
    for i in range(1, 6):
        lines = [f"def function_{i}():"]
        lines.extend([f"    x_{j} = {j}" for j in range(200)])
        lines.append(f"    return x_199")
        funcs.append("\n".join(lines))

    large_code = "\n\n".join(funcs)
    chunker = SemanticCodeChunker(default_max_tokens=500)
    chunks = chunker.chunk_file("large_app.py", large_code, max_tokens=500)

    assert len(chunks) >= 5
    assert all(c.file_path == "large_app.py" for c in chunks)
    assert any("function_1" in c.content for c in chunks)
    assert any("function_5" in c.content for c in chunks)


def test_large_repository_byte_limit_enforcement(tmp_path):
    repo = tmp_path / "large_repo"
    repo.mkdir()

    # Create 10 files of 100 KB each (1 MB total)
    for i in range(10):
        (repo / f"file_{i}.py").write_text("x = 1\n" * 10000)

    # Set MAX_REPO_TOTAL_BYTES to 300 KB
    with pytest.MonkeyPatch.context() as m:
        m.setattr(Config, "MAX_REPO_TOTAL_BYTES", 300_000)
        scanner = CodebaseScanner(str(repo))
        files = scanner.get_files()

        # Should cap file list before reading all 1 MB
        assert len(files) < 10


def test_repeated_identical_chunk_deduplication():
    chunk1 = CodeChunk.create("app.py", 1, 10, "def foo():\n    return 1")
    chunk2 = CodeChunk.create("app.py", 1, 10, "def foo():\n    return 1")
    chunk3 = CodeChunk.create("app.py", 11, 20, "def bar():\n    return 2")

    chunker = SemanticCodeChunker()
    unique = chunker.deduplicate_chunks([chunk1, chunk2, chunk3])

    assert len(unique) == 2
    assert unique[0].chunk_id != unique[1].chunk_id


def test_context_window_limit_overflow_prevention():
    lines = [f"line_{i} = {i}" for i in range(1000)]
    long_text = "\n".join(lines)

    chunker = SemanticCodeChunker(default_max_tokens=300)
    chunks = chunker.chunk_file("script.py", long_text, max_tokens=300)

    for c in chunks:
        assert c.token_count <= 400  # bounded chunk size


def test_budget_and_token_telemetry_tracking():
    ctx = ReviewContext()
    ctx.record_tokens("security_auditor", prompt_tokens=1000, completion_tokens=200, estimated_cost=0.005)
    ctx.record_tokens("quality_auditor", prompt_tokens=800, completion_tokens=150, estimated_cost=0.003)

    assert ctx.total_prompt_tokens == 1800
    assert ctx.total_completion_tokens == 350
    assert ctx.tokens_by_agent["security_auditor"]["total_tokens"] == 1200
    assert ctx.tokens_by_agent["quality_auditor"]["total_tokens"] == 950
    assert round(ctx.estimated_cost_usd, 4) == 0.008


def test_tenant_isolated_response_caching():
    cache = IsolatedResponseCache(ttl_seconds=60)
    input_payload = {"file": "auth.py", "lines": 50}

    cache.put(
        tenant_id="org_alpha",
        prompt_id="sec_v1",
        prompt_version="1.0.0",
        model="gpt-4o",
        input_payload=input_payload,
        response=["finding_1"],
    )

    # Same tenant & payload -> hit
    cached = cache.get("org_alpha", "sec_v1", "1.0.0", "gpt-4o", input_payload)
    assert cached == ["finding_1"]

    # Different tenant -> miss (tenant isolation preserved!)
    diff_tenant = cache.get("org_beta", "sec_v1", "1.0.0", "gpt-4o", input_payload)
    assert diff_tenant is None

    # Modified payload -> miss
    diff_payload = cache.get("org_alpha", "sec_v1", "1.0.0", "gpt-4o", {"file": "auth.py", "lines": 51})
    assert diff_payload is None


def test_concurrency_bounds_enforcement():
    pipeline = ReviewPipeline(max_concurrent_files=20)
    assert pipeline.max_concurrent_files <= Config.MAX_CONCURRENT_FILES
