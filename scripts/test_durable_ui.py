"""Real browser + real local graph/stores using current folder-based IDE (scripted provider)."""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "browser"))

from playwright.sync_api import sync_playwright, expect


def pick_folder(page, target: Path):
    def _forward_pick(route):
        headers = {k: v for k, v in route.request.headers.items() if k.lower() != "content-length"}
        headers["content-type"] = "application/json"
        api_res = page.request.post(
            "http://127.0.0.1:8019/workspace",
            headers=headers,
            data=json.dumps({"path": str(target.resolve())}),
        )
        route.fulfill(status=api_res.status, body=api_res.body(), content_type="application/json")

    page.route("**/workspace/pick", _forward_pick, times=1)
    page.get_by_role("button", name="Open local folder", exact=True).click()


def main():
    destination = ROOT / "tasks" / "evidence"
    destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=ROOT / ".tools", prefix="ui-source-") as directory, sync_playwright() as engine:
        source = Path(directory)
        (source / "service.py").write_text("def first(items):\n    return items[0]\n", encoding="utf-8")
        (source / ".env").write_text("fixture-secret-never-uploaded", encoding="utf-8")
        (source / "dist").mkdir()
        (source / "dist/bundle.js").write_text("generated", encoding="utf-8")
        browser = engine.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors, requests = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append((request.method, request.url)))

        page.goto("http://127.0.0.1:5173")
        page.wait_for_load_state("networkidle")
        pick_folder(page, source)
        expect(page.locator('#source-files [role="treeitem"][title="service.py"]')).to_be_visible(timeout=10000)

        expect(page.get_by_role("button", name="Run review")).to_be_enabled()
        page.get_by_role("button", name="Run review").click()
        expect(page.locator(".job-bar > code")).to_contain_text("Job ID:", timeout=20000)
        job_id = page.locator(".job-bar > code").inner_text().split(": ")[1]
        expect(page.get_by_role("heading", name="Uncertain high-impact candidates (1)")).to_be_visible(timeout=20000)
        expect(page.get_by_role("heading", name="Confirmed defects (0)")).to_be_visible()
        expect(page.get_by_role("heading", name="Advisories (0)")).to_be_visible()

        with page.expect_download() as saved:
            page.get_by_role("button", name="Download JSON").click()
        report = json.loads(Path(saved.value.path()).read_text(encoding="utf-8"))
        assert len(report["uncertain_high_impact_candidates"]) == 1
        with page.expect_download() as saved:
            page.get_by_role("button", name="Download Markdown").click()
        assert "Uncertain" in Path(saved.value.path()).read_text(encoding="utf-8")

        # Reopen job without workspace open and verify Open source still loads from /api/jobs/{id}/source.
        page.reload()
        page.wait_for_load_state("networkidle")
        page.get_by_label("Job ID", exact=True).fill(job_id)
        page.get_by_role("button", name="Open job", exact=True).click()
        expect(page.get_by_role("heading", name="Uncertain high-impact candidates (1)")).to_be_visible(timeout=20000)
        page.get_by_role("button", name="Open source", exact=True).click()
        expect(page.locator("#source-pane .monaco-editor")).to_be_visible(timeout=10000)

        for width in (320, 768, 1024, 1440):
            page.set_viewport_size({"width": width, "height": 640 if width == 320 else 1000})
            if width <= 900:
                page.get_by_role("button", name="Review", exact=True).click()
            expect(page.get_by_role("heading", name="Review results")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"Overflow at {width}"

        assert errors == [], errors
        assert not page.evaluate("Object.keys(localStorage).length || Object.keys(sessionStorage).length")

        # Accepted POST with a lost response retains recovery intent cleanly.
        pick_folder(page, source)
        expect(page.get_by_role("button", name="Run review")).to_be_enabled(timeout=10000)
        def lose_response(route):
            route.fetch()
            route.abort("failed")
        page.route("**/api/jobs", lose_response, times=1)
        page.get_by_role("button", name="Run review").click()
        expect(page.get_by_role("button", name="Retry same submission")).to_be_enabled(timeout=20000)
        page.get_by_role("button", name="Retry same submission").click()
        expect(page.get_by_role("heading", name="Uncertain high-impact candidates (1)")).to_be_visible(timeout=20000)
        print("PASS: folder workspace, exports, reload/Open source fallback, responsive widths, and lost-response recovery")


if __name__ == "__main__":
    main()
