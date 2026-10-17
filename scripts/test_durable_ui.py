"""Real browser + real local graph/stores, only the model provider is scripted."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright, expect


def connect(page):
    page.get_by_text('Service connection', exact=True).click()
    page.get_by_label('Service URL').fill('http://127.0.0.1:8019')
    page.get_by_label('API key', exact=True).fill('browser-fixture-key')
    page.get_by_role('button', name='Connect', exact=True).click()


def main():
    destination = Path('tasks/evidence')
    with TemporaryDirectory(dir='.tools', prefix='ui-source-') as directory, sync_playwright() as engine:
        source = Path(directory)
        (source / 'service.py').write_text('def first(items):\n    return items[0]\n', encoding='utf-8')
        (source / '.env').write_text('fixture-secret-never-uploaded', encoding='utf-8')
        (source / 'dist').mkdir()
        (source / 'dist/bundle.js').write_text('generated', encoding='utf-8')
        browser = engine.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors, requests, regressions = [], [], []
        def check_case(name, check):
            try:
                check()
            except AssertionError as error:
                regressions.append(name)
                print('REGRESSION', name, str(error).splitlines()[0], flush=True)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: requests.append((request.method, request.url)))
        page.on('requestfailed', lambda request: print('REQUEST FAILED', request.method, request.url, request.failure, flush=True))
        page.on('console', lambda message: print('BROWSER', message.type, message.text, flush=True) if message.type == 'error' else None)
        page.on('response', lambda response: print('SERVICE RESPONSE', response.status, response.url, flush=True) if response.status >= 400 else None)
        page.goto('http://127.0.0.1:5173')
        page.wait_for_load_state('networkidle')
        connect(page)
        page.get_by_text('Service connection', exact=True).click()
        page.locator('input[type=file]').set_input_files(str(source.resolve()))
        expect(page.get_by_role('button', name='Run review')).to_be_enabled()
        page.get_by_role('button', name='Run review').click()
        expect(page.locator('.job-bar > code')).to_contain_text('Job ID:', timeout=20000)
        job_id = page.locator('.job-bar > code').inner_text().split(': ')[1]
        expect(page.get_by_role('heading', name='Uncertain high-impact candidates (1)')).to_be_visible(timeout=20000)
        page.get_by_label('Job ID', exact=True).fill(job_id)
        page.get_by_role('button', name='Open job', exact=True).click()
        expect(page.get_by_role('button', name='Open job', exact=True)).to_be_enabled()
        check_case('opening a completed job clears the local folder selection', lambda: expect(page.get_by_role('button', name='Run review')).to_be_disabled())
        # Detach the browser while the job is running; reopen by identity.
        page.reload()
        page.wait_for_load_state('networkidle')
        connect(page)
        page.get_by_text('Service connection', exact=True).click()
        page.get_by_label('Job ID', exact=True).fill(job_id)
        page.get_by_role('button', name='Open job', exact=True).click()
        expect(page.get_by_role('heading', name='Uncertain high-impact candidates (1)')).to_be_visible(timeout=20000)
        expect(page.get_by_role('heading', name='Confirmed defects (0)')).to_be_visible()
        expect(page.get_by_role('heading', name='Advisories (0)')).to_be_visible()
        expect(page.get_by_text('dist/bundle.js: excluded_source')).to_be_visible()
        expect(page.get_by_text('.env: excluded_source')).to_be_visible()
        page.get_by_role('button', name='Open source', exact=True).click()
        expect(page.get_by_label('Line 2', exact=True)).to_have_text('    return items[0]')
        with page.expect_download() as saved:
            page.get_by_role('button', name='Download JSON').click()
        report = json.loads(Path(saved.value.path()).read_text(encoding='utf-8'))
        assert len(report['uncertain_high_impact_candidates']) == 1
        with page.expect_download() as saved:
            page.get_by_role('button', name='Download Markdown').click()
        assert 'Uncertain' in Path(saved.value.path()).read_text(encoding='utf-8')
        with page.expect_download() as saved:
            page.get_by_role('button', name='Download PDF').click(timeout=5000)
        import pymupdf
        with pymupdf.open(saved.value.path()) as document:
            assert 'Uncertain high-impact candidates (1)' in ''.join(leaf.get_text() for leaf in document)
            assert job_id in saved.value.suggested_filename
        for width in (320, 768, 1024, 1440):
            page.set_viewport_size({'width': width, 'height': 640 if width == 320 else 1000})
            if width <= 900:
                page.get_by_role('button', name='Review', exact=True).click()
            expect(page.get_by_role('heading', name='Review results')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'Overflow at {width}'
            assert page.locator('#review-results').bounding_box()['height'] > 100, f'Results collapsed at {width}'
            page.screenshot(path=str(destination / f'durable-ui-{width}.png'), full_page=True)
        assert errors == [], errors
        assert sum(method == 'POST' and url.endswith('/api/jobs') for method, url in requests) == 1
        assert not any('/api/review' in url or '/api/fs/' in url or '/ws/review' in url or url.endswith('/cancel') for _, url in requests)
        assert not page.evaluate('Object.keys(localStorage).length || Object.keys(sessionStorage).length')
        # Accepted POST with a lost response must retain its only recovery intent.
        page.set_viewport_size({'width': 320, 'height': 480})
        page.locator('input[type=file]').set_input_files(str(source.resolve()))
        def lose_response(route):
            route.fetch()  # Real service accepts the intent; the viewer sees no response.
            route.abort('failed')
        page.route('**/api/jobs', lose_response, times=1)
        page.get_by_role('button', name='Run review').click()
        expect(page.get_by_role('button', name='Retry same submission')).to_be_enabled(timeout=20000)
        intent = page.locator('.submission-intent').inner_text()
        page.get_by_text('Service connection', exact=True).click()
        check_case('unknown submission guards Connect', lambda: expect(page.get_by_role('button', name='Connect', exact=True)).to_be_disabled())
        check_case('unknown submission guards Open job', lambda: expect(page.get_by_role('button', name='Open job', exact=True)).to_be_disabled())
        for button in page.get_by_role('button', name='Open local folder', exact=True, include_hidden=True).all():
            check_case('unknown submission guards every folder control', lambda: expect(button).to_be_disabled())
        assert page.locator('.submission-intent').inner_text() == intent
        target = page.locator('#review-results')
        target.scroll_into_view_if_needed(timeout=5000)
        bounds = target.bounding_box()
        workspace = page.locator('.body').bounding_box()
        def check_bounds():
            assert workspace and workspace['height'] >= 200 and bounds and 0 <= bounds['y'] < 480, f'Expanded controls hide the review workspace: body={workspace}, results={bounds}'
        check_case('expanded controls remain usable at 320x480', check_bounds)
        page.screenshot(path=str(destination / 'durable-ui-short-expanded.png'), full_page=True)
        page.get_by_text('Service connection', exact=True).click()
        page.get_by_role('button', name='Retry same submission').click()
        expect(page.get_by_role('heading', name='Uncertain high-impact candidates (1)')).to_be_visible(timeout=20000)
        assert sum(method == 'POST' and url.endswith('/api/jobs') for method, url in requests) == 3
        page.screenshot(path=str(destination / 'durable-ui-short-recovery.png'), full_page=True)
        assert regressions == [], regressions
        print('PASS: real browser capture, authenticated jobs, viewer disconnect/reopen, separate reports, immutable source, JSON/Markdown/PDF exports, four responsive widths, lost-response recovery, no legacy requests, no application exceptions or stored credentials')
        browser.close()


if __name__ == '__main__':
    main()
