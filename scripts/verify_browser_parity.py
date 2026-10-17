"""Real Chrome + canonical ASGI service smoke; scripted provider, no model network."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def serve(runtime):
    import uvicorn
    from tests.test_canonical_workflow import ReviewProvider
    from tests.test_control_agents import MODELS
    from devwatch.review.service import ServiceSettings, create_app
    uvicorn.run(create_app(settings=ServiceSettings(runtime_root=Path(runtime), models=MODELS), provider=ReviewProvider()),
                host="127.0.0.1", port=8998, log_level="warning")


def run():
    sys.path.insert(0, str(ROOT / ".tools" / "browser"))
    from playwright.sync_api import sync_playwright, expect
    def wait(url):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                with urlopen(url, timeout=1):
                    return
            except OSError:
                time.sleep(.1)
        raise TimeoutError("Local verification server did not start")
    with tempfile.TemporaryDirectory(prefix="devwatch-browser-") as directory:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with open(Path(directory) / "servers.log", "w") as output:
            service = subprocess.Popen([sys.executable, "-m", "scripts.verify_browser_parity", "--serve", directory], cwd=ROOT,
                stdout=output, stderr=output, creationflags=flags)
            vite = subprocess.Popen(["node", str(ROOT / "frontend/node_modules/vite/bin/vite.js"), "--host", "127.0.0.1", "--port", "5173", "--strictPort"],
                cwd=ROOT / "frontend", stdout=output, stderr=output, creationflags=flags)
            try:
                wait("http://127.0.0.1:8998/openapi.json"); wait("http://127.0.0.1:5173")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel="chrome", headless=True)
                    try:
                        page = browser.new_page(viewport={"width": 320, "height": 480})
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto("http://127.0.0.1:5173"); page.wait_for_load_state("networkidle")
                        page.get_by_text('Service connection', exact=True).click()
                        page.get_by_label("Service URL").fill("http://127.0.0.1:8998")
                        page.get_by_role("button", name="Connect", exact=True).click()
                        page.get_by_text('Service connection', exact=True).click()
                        source = Path(directory) / "source"
                        source.mkdir()
                        (source / "service.py").write_text("def first(items):\n    return items[0]\n", encoding="utf-8")
                        page.locator('input[type=file]').set_input_files(str(source))
                        page.get_by_role("button", name="Run review").click()
                        expect(page.get_by_role("button", name="Download JSON")).to_be_visible(timeout=15000)
                        for label in ("Download JSON", "Download Markdown", "Download PDF"):
                            with page.expect_download() as saved:
                                page.get_by_role("button", name=label, exact=True).click()
                            assert saved.value.failure() is None
                        page.get_by_text('Recent events', exact=False).click()
                        page.get_by_role('button', name='View tool evidence', exact=True).first.click()
                        expect(page.get_by_role('region', name='Tool evidence')).to_contain_text('read_source')
                        job = page.locator('.job-bar > code').inner_text().split()[-1]
                        page.get_by_role("button", name="Files", exact=True).click()
                        page.get_by_role("button", name="Open service.py").click()
                        expect(page.locator('#source-pane')).to_be_visible()
                        page.locator('.skip-link').focus()
                        page.keyboard.press("Enter")
                        expect(page.locator('#review-results')).to_be_visible()
                        expect(page.locator('#review-results')).to_be_focused()
                        page.reload(); page.wait_for_load_state("networkidle")
                        page.get_by_text('Service connection', exact=True).click()
                        page.get_by_label("Service URL").fill("http://127.0.0.1:8998")
                        page.get_by_role("button", name="Connect", exact=True).click()
                        page.get_by_label("Job ID", exact=True).fill(job)
                        page.get_by_role("button", name="Open job", exact=True).click()
                        expect(page.get_by_role("button", name="Download PDF")).to_be_visible(timeout=10000)
                        for width in (320, 768, 1024, 1440):
                            page.set_viewport_size({"width": width, "height": 900})
                            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        assert not errors, errors
                        print(json.dumps({"browser": "Chrome", "capture": True, "exports": ["json", "markdown", "pdf"],
                            "reopen": True, "immutable_source": True, "narrow_skip_link": True, "console_errors": 0}))
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
