"""Offline PDF visual evidence using actual service results and a long fixture."""
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
import pymupdf

from devwatch.review.contracts import Coverage, ReportDraft
from devwatch.review.finalization import FinalAcceptanceGate
from devwatch.review.pdf import render_accepted_pdf
from tests.test_review_service import ALICE, app, completed, submit


def save(name, data):
    destination = Path("output/pdf")
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"devwatch-{name}-sample.pdf"
    with path.open("xb") as stream:
        stream.write(data)
    with pymupdf.open(stream=data, filetype="pdf") as document:
        for index, page in enumerate(document, 1):
            page.get_pixmap(matrix=pymupdf.Matrix(1.25, 1.25)).save(f"tasks/evidence/pdf-{name}-{index}.png")
        print(f"{path}: {len(document)} pages; all pages rendered")


def main():
    with TemporaryDirectory(dir=".tools", prefix="pdf-runtime-") as root:
        with TestClient(app(Path(root))) as client:
            identity, _ = submit(client)
            assert completed(client, identity)["status"] == "completed"
            response = client.get(f"/api/jobs/{identity}/report?format=pdf", headers=ALICE)
            assert response.status_code == 200
            save("canonical", response.content)
    coverage = Coverage(inspected_files=[f"package/{index:03d}/" + "x" * 170 + ".py" for index in range(70)],
        skipped={"generated.js": "excluded_source"}, failed={"benchmark": "tool_unavailable"})
    report = ReportDraft(snapshot_id="coverage-fixture", summary='<img src="https://invalid.test/secret"/> café 你好; literal "a  b" retains two spaces.',
        coverage=coverage, limitations=["Final coverage limitation. No benchmark ran."])
    save("coverage", render_accepted_pdf(FinalAcceptanceGate({}).accept(report, [])))


if __name__ == "__main__":
    main()
