"""Real Chrome + local service smoke for the folder-based web IDE.

Uses a scripted provider (no model network). Verifies: set workspace by path,
lazy explorer with 5,000+ entries, full 1 MB file in Monaco, run a review, report
renders, finding click-through, reopen job after reload, no horizontal overflow.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SERVICE_PORT = 8998
VITE_PORT = 5173
BIG_FILE_BYTES = 1_000_000
IGNORED_FILE_COUNT = 5_200


def serve(runtime):
    import uvicorn
    from tests.test_canonical_workflow import ReviewProvider
    from tests.test_control_agents import MODELS
    from backend.review.service import ServiceSettings, create_app
    uvicorn.run(create_app(settings=ServiceSettings(runtime_root=Path(runtime), models=MODELS), provider=ReviewProvider()),
                host="127.0.0.1", port=SERVICE_PORT, log_level="warning")


def build_workspace(source: Path) -> None:
    source.mkdir()
    (source / "service.py").write_text("def first(items):\n    return items[0]\n", encoding="utf-8")
    line = "x" * 99 + "\n"
    (source / "big.txt").write_text(line * (BIG_FILE_BYTES // len(line)), encoding="utf-8")
    vendor = source / "node_modules"
    for index in range(IGNORED_FILE_COUNT):
        package = vendor / f"pkg{index // 100:03d}"
        package.mkdir(parents=True, exist_ok=True)
        (package / f"mod{index:05d}.js").write_text("module.exports = 1\n", encoding="utf-8")


def wait(url):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1):
                return
        except OSError:
            time.sleep(.2)
    raise TimeoutError(f"Local verification server did not start: {url}")


def run():
    sys.path.insert(0, str(ROOT / ".tools" / "browser"))
    from playwright.sync_api import expect, sync_playwright
    with tempfile.TemporaryDirectory(prefix="devwatch-browser-") as directory:
        source = Path(directory) / "source"
        build_workspace(source)
        big_size = (source / "big.txt").stat().st_size
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with open(Path(directory) / "servers.log", "w") as output:
            service = subprocess.Popen([sys.executable, "-m", "scripts.verify_browser_parity", "--serve", str(Path(directory) / "runtime")],
                cwd=ROOT, stdout=output, stderr=output, creationflags=flags)
            vite = subprocess.Popen(["node", str(ROOT / "frontend/node_modules/vite/bin/vite.js"), "--host", "127.0.0.1",
                                     "--port", str(VITE_PORT), "--strictPort"],
                cwd=ROOT / "frontend",
                env={**os.environ, "DEVWATCH_SERVICE_URL": f"http://127.0.0.1:{SERVICE_PORT}", "DEVWATCH_API_KEY": ""},
                stdout=output, stderr=output, creationflags=flags)
            try:
                wait(f"http://127.0.0.1:{SERVICE_PORT}/openapi.json"); wait(f"http://127.0.0.1:{VITE_PORT}")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel="chrome", headless=True)
                    try:
                        page = browser.new_page(viewport={"width": 1440, "height": 900})
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(f"http://127.0.0.1:{VITE_PORT}"); page.wait_for_load_state("networkidle")

                        def pick_folder(target: Path):
                            resolved = target.resolve()
                            page.get_by_role("button", name="Open local folder", exact=True).click()
                            dialog = page.get_by_role("dialog", name="Open local folder")
                            expect(dialog).to_be_visible(timeout=10000)
                            dialog.get_by_role("button", name=resolved.anchor, exact=True).click()
                            subdirs = dialog.get_by_label("Subfolders")
                            filter_box = dialog.get_by_label("Filter folders")
                            for part in resolved.parts[1:]:
                                filter_box.fill(part)
                                subdirs.get_by_role("button", name=part, exact=True).click()
                            dialog.get_by_role("button", name="Open Selected Folder", exact=True).click()

                        started = time.monotonic()
                        pick_folder(source)
                        tree = page.locator("#source-files")
                        def tree_item(rel_path: str):
                            return tree.locator(f'[role="treeitem"][title="{rel_path}"]')

                        expect(tree_item("service.py")).to_be_visible(timeout=10000)
                        root_seconds = time.monotonic() - started
                        expect(tree_item("node_modules")).to_be_visible()

                        # 1 MB file opens in full in Monaco before expanding huge folder.
                        tree_item("big.txt").click()
                        expect(page.locator("#source-pane .monaco-editor")).to_be_visible(timeout=20000)
                        expect(page.locator("#source-pane")).not_to_contain_text("too large")

                        # Lazy expansion of an ignored (dimmed) folder with 5,000+ descendants.
                        tree_item("node_modules").click()
                        expect(tree_item("node_modules/pkg000")).to_be_visible(timeout=10000)
                        tree_item("node_modules/pkg000").click()
                        expect(tree_item("node_modules/pkg000/mod00000.js")).to_be_visible(timeout=10000)

                        # Run a review against the live folder and wait for the report.
                        page.get_by_role("button", name="Run review", exact=True).click()
                        expect(page.get_by_role("button", name="Download JSON")).to_be_visible(timeout=30000)
                        results = page.locator("#review-results")
                        expect(results).to_contain_text("Report overview")
                        for label in ("Download JSON", "Download Markdown"):
                            with page.expect_download() as saved:
                                page.get_by_role("button", name=label, exact=True).click()
                            assert saved.value.failure() is None

                        # Finding click-through opens the file at its line range.
                        results.get_by_role("button", name="Open source").first.click()
                        expect(page.locator("#source-pane")).to_contain_text("service.py", timeout=10000)

                        job = page.locator(".job-bar > code").inner_text().split()[-1]
                        page.reload(); page.wait_for_load_state("networkidle")
                        expect(page.get_by_role("button", name="Download JSON")).to_be_visible(timeout=10000)

                        # Clear view via New review and reopen directly from History sidebar card.
                        page.get_by_role("button", name="New review", exact=True).click()
                        page.get_by_role("button", name="History", exact=True).click()
                        page.locator(f'.history-card[data-job-id="{job}"]').click()
                        expect(page.get_by_role("button", name="Download JSON")).to_be_visible(timeout=10000)
                        results.get_by_role("button", name="Open source").first.click()
                        expect(page.locator("#source-pane .monaco-editor")).to_be_visible(timeout=10000)

                        for width in (320, 768, 1024, 1440):
                            page.set_viewport_size({"width": width, "height": 900})
                            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
                        assert not errors, errors
                        print(json.dumps({"browser": "Chrome", "workspace_entries": IGNORED_FILE_COUNT + 2,
                            "root_tree_seconds": round(root_seconds, 2), "lazy_expand": True,
                            "full_file_bytes": big_size, "review_report": True, "exports": ["json", "markdown"],
                            "finding_click_through": True, "reopen_job": True, "console_errors": 0}))
                    finally:
                        browser.close()
            finally:
                for process in (vite, service):
                    process.terminate()
                for process in (vite, service):
                    process.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve")
    args = parser.parse_args()
    serve(args.serve) if args.serve else run()
