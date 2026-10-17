"""Accepted-only PDFs remain literal, deterministic and complete across pages."""
import importlib
from concurrent.futures import ThreadPoolExecutor
import threading

import pymupdf
import pytest

from devwatch.review.contracts import Coverage, ReportDraft
from devwatch.review.finalization import FinalAcceptanceGate


def renderer():
    assert importlib.util.find_spec("devwatch.review.pdf"), "Accepted PDF renderer is missing"
    return importlib.import_module("devwatch.review.pdf").render_accepted_pdf


def test_pdf_requires_acceptance_and_preserves_literal_model_text():
    render = renderer()
    draft = ReportDraft(snapshot_id="snapshot-one", summary='<img src="https://invalid.test/secret"/> café 你好',
                        coverage=Coverage(inspected_files=["service.py"], inspected_symbols=["first"],
                                          skipped={"generated.js": "excluded_source"}, failed={"task": "tool_unavailable"}),
                        limitations=["Tests did not run"])
    with pytest.raises(TypeError):
        render(draft)
    accepted = FinalAcceptanceGate({}).accept(draft, [])
    first = render(accepted)
    assert first == render(accepted)
    with pymupdf.open(stream=first, filetype="pdf") as document:
        text = "".join(page.get_text() for page in document)
        assert '<img src="https://invalid.test/secret"/>' in text
        assert "café" in text and r"\u4f60\u597d" in text
        for value in ("snapshot-one", "Confirmed defects (0)", "Uncertain high-impact candidates (0)",
                      "Advisories (0)", "service.py", "first", "generated.js", "excluded_source",
                      "tool_unavailable", "Tests did not run", "Page 1"):
            assert value in text
        assert all(not page.get_links() and not list(page.annots() or []) for page in document)


def test_long_pdf_wraps_identifiers_without_losing_coverage_or_footer():
    render = renderer()
    paths = [f"package/{index:03d}/" + "x" * 170 + ".py" for index in range(70)]
    accepted = FinalAcceptanceGate({}).accept(ReportDraft(snapshot_id="long-snapshot", summary="Long review",
        coverage=Coverage(inspected_files=paths), limitations=["Final coverage limitation"]), [])
    with pymupdf.open(stream=render(accepted), filetype="pdf") as document:
        assert len(document) >= 3
        text = "".join(page.get_text() for page in document)
        assert "Final coverage limitation" in text
        compact = "".join(text.split())
        assert all(path in compact for path in paths)
        for index, page in enumerate(document, 1):
            assert f"Page {index}" in page.get_text()
            for block in page.get_text("blocks"):
                assert 30 <= block[0] < block[2] <= page.rect.width - 30
                assert 25 <= block[1] < block[3] <= page.rect.height - 25


def test_concurrent_mixed_glyph_documents_do_not_share_mutating_font_state(monkeypatch):
    from reportlab.platypus import SimpleDocTemplate
    render = renderer()
    active = peak = 0
    counter = threading.Lock()
    original = SimpleDocTemplate.build
    def observed_build(document, *args, **kwargs):
        nonlocal active, peak
        with counter:
            active += 1
            peak = max(peak, active)
        try:
            threading.Event().wait(.04)  # Ensure overlapping requests reach the actual font builder.
            return original(document, *args, **kwargs)
        finally:
            with counter:
                active -= 1
    monkeypatch.setattr(SimpleDocTemplate, "build", observed_build)
    reports = [FinalAcceptanceGate({}).accept(ReportDraft(snapshot_id=f"mixed-{index}",
        summary=text, coverage=Coverage()), []) for index, text in enumerate(["café", "naïve", "£ coût", "你好"])]
    with ThreadPoolExecutor(max_workers=4) as pool:
        documents = list(pool.map(render, reports))
    assert peak == 1, "Shared TTFont builds overlapped"
    for index, data in enumerate(documents):
        with pymupdf.open(stream=data, filetype="pdf") as document:
            assert f"mixed-{index}" in "".join(page.get_text() for page in document)


def test_significant_spaces_in_report_string_literals_are_preserved():
    accepted = FinalAcceptanceGate({}).accept(ReportDraft(snapshot_id="spaces", summary='Expected input is "a  b"; actual input is "a b".',
                                                         coverage=Coverage()), [])
    with pymupdf.open(stream=renderer()(accepted), filetype="pdf") as document:
        text = "".join(page.get_text() for page in document)
        assert '"a  b"' in text and '"a b"' in text
