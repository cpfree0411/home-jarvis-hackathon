#!/usr/bin/env python3
"""No-credit browser contracts: keyboard, focus, empty states, errors, kiosk and embedding."""
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from otaku_gallery.app import build_app
from otaku_gallery.config import Config
from otaku_gallery.server import make_server, serve_in_thread
from scripts.ui_smoke import StubWriter


def main():
    config = replace(Config.from_env(), evidence_mode='fixture')
    app = build_app(config, writer=StubWriter())
    server = make_server(app, '127.0.0.1', 0)
    serve_in_thread(server)
    base = 'http://127.0.0.1:%d/' % server.server_address[1]
    checks = []

    def check(name, passed):
        checks.append({'name': name, 'pass': bool(passed)})
        print(('PASS ' if passed else 'FAIL ') + name)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1024, 'height': 600})
        errors = []
        page.on('pageerror', lambda error: errors.append(type(error).__name__))
        page.goto(base + '?autoplay=0&kiosk=1&bg=host')
        page.wait_for_selector('#app[data-state=ready]')
        titles = []
        for _ in range(8):
            titles.append(page.inner_text('#cap-title'))
            page.press('body', 'ArrowRight')
        check('all eight artworks browse and wrap', len(set(titles)) == 8 and page.inner_text('#cap-title') == titles[0])
        check('artwork has accessible description', bool(page.get_attribute('#stage', 'aria-label')))
        check('embedding background option active', 'host-bg' in page.get_attribute('body', 'class'))
        page.press('body', ' ')
        check('space resumes slideshow', page.get_attribute('#play', 'aria-pressed') == 'false')
        page.press('body', ' ')
        check('space pauses slideshow', page.get_attribute('#play', 'aria-pressed') == 'true')
        page.press('body', 'f')
        page.reload()
        page.wait_for_selector('#app[data-state=ready]')
        check('favorite survives reload', page.get_attribute('#fav', 'aria-pressed') == 'true')
        page.press('body', 'i')
        page.click('#filter-tags button:has-text("Favorites")')
        check('favorite filter narrows gallery', page.inner_text('#counter').startswith('1 / 1'))
        page.press('body', 'Escape')
        page.press('body', 'f')
        check('empty favorites message is English', 'no favorites' in page.inner_text('#cap-title'))
        page.press('body', 'i')
        page.click('#filter-tags button:text-is("All")')
        page.press('body', 'Escape')
        check('all filter restores gallery', page.inner_text('#counter').startswith('1 / 8'))
        page.press('#research-open', 'r')
        check('research search receives focus', page.locator('.rs-input').evaluate('(e) => document.activeElement === e'))
        page.keyboard.press('Shift+Tab')
        check('modal keeps keyboard focus inside', page.locator('#research').evaluate('(e) => e.contains(document.activeElement)'))
        page.fill('.rs-input', 'Cyberpunk')
        page.press('.rs-input', 'Enter')
        page.wait_for_selector('.rs-article:not([hidden]) h1')
        check('typed query renders source-backed result', page.inner_text('.rs-article h1') == 'Cyberpunk')
        page.locator('.rs-sources a').first.click()
        check('kiosk source link shows address', 'https://en.wikipedia.org/' in page.inner_text('.rs-toast'))
        page.press('body', 'Escape')
        check('closing research restores opener focus', page.locator('#research-open').evaluate('(e) => document.activeElement === e'))
        # Deterministic terminal-state contracts, exercising the real form and renderer.
        scenarios = [
            ('unsafe', {'status': 'unsafe'}, 'That topic is not available here'),
            ('not-found', {'status': 'not_found', 'sources': []}, 'No matching sources found'),
            ('rate-limit', {'status': 'rate_limited'}, 'Please wait a moment'),
            ('ambiguous', {'status': 'ambiguous', 'candidates': [{'label': 'Genre', 'note': 'Choose a subject', 'query': 'Cyberpunk'}], 'sources': []}, 'Which one did you mean?'),
        ]
        for name, result, title in scenarios:
            payload = {'ok': True, 'id': 'contract1234', 'status': 'done', 'query': name, 'page': result, 'retry_after': 3}
            page.route('**/api/research', lambda route, request, value=payload: route.fulfill(json=value))
            page.press('body', 'r')
            page.fill('.rs-input', name)
            page.press('.rs-input', 'Enter')
            page.wait_for_selector('.rs-article:not([hidden]) .rs-notice h2')
            check(name + ' has useful English state', title in page.inner_text('.rs-article'))
            page.press('body', 'Escape')
            page.unroute('**/api/research')
        page.route('**/api/research', lambda route: route.fulfill(status=503, json={'ok': False, 'error': {'code': 'research_disabled', 'message': 'The Research Guide is turned off on this server.'}}))
        page.press('body', 'r')
        page.fill('.rs-input', 'Example')
        page.press('.rs-input', 'Enter')
        page.wait_for_selector('.rs-retry')
        check('HTTP errors offer an English retry', 'turned off' in page.inner_text('.rs-article'))
        page.press('body', 'Escape')
        page.unroute('**/api/research')
        page.route('**/api/research', lambda route: route.abort())
        page.press('body', 'r')
        page.fill('.rs-input', 'Example')
        page.press('.rs-input', 'Enter')
        page.wait_for_selector('.rs-retry')
        check('network failure is understandable', 'Check your connection' in page.inner_text('.rs-article'))
        page.press('body', 'Escape')
        page.unroute('**/api/research')
        # Responsive research header, not just the background gallery.
        for width, height in [(390, 844), (1024, 600), (1920, 1080)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.press('body', 'r')
            check('research controls fit %dx%d' % (width, height), page.locator('.rs-go').evaluate('(e) => { const r=e.getBoundingClientRect(); return r.left>=0 && r.right<=innerWidth && r.bottom<=innerHeight; }'))
            page.press('body', 'Escape')
        check('no browser exceptions', not errors)
        # On-screen touch keyboard on the 1024x600 kiosk.
        touch = browser.new_context(viewport={'width': 1024, 'height': 600}, has_touch=True).new_page()
        touch_errors = []
        touch.on('pageerror', lambda error: touch_errors.append(type(error).__name__))
        touch.on('console', lambda msg: msg.type == 'error' and touch_errors.append(msg.text))
        touch.goto(base + '?autoplay=0&kiosk=1')
        touch.wait_for_selector('#app[data-state=ready]')
        touch.tap('#research-open')
        touch.wait_for_selector('#research:not([hidden])')
        check('touch keyboard stays hidden until the field is touched', touch.is_hidden('.rs-keyboard'))
        touch.tap('.rs-input')
        check('touching the search field shows the keyboard', touch.is_visible('.rs-keyboard'))

        def key(name):
            touch.tap('.rs-key[data-key="%s"]' % name)

        for k in ['shift', 'c', 'y', 'b', 'e', 'r', 'space']:
            key(k)
        check('shift and space type English', touch.input_value('.rs-input') == 'Cyber ')
        key('back')
        for k in 'punk':
            key(k)
        check('backspace edits typed text', touch.input_value('.rs-input') == 'Cyberpunk')
        layout = touch.evaluate('''() => {
          const r = (s) => document.querySelector(s).getBoundingClientRect(), kb = r('.rs-keyboard');
          const keys = [...document.querySelectorAll('.rs-key')].filter((k) => k.offsetParent).map((k) => k.getBoundingClientRect());
          return {clear: ['.rs-input', '.rs-go', '.rs-close'].every((s) => r(s).bottom <= kb.top),
                  inside: kb.bottom <= innerHeight && kb.left >= 0 && kb.right <= innerWidth,
                  overflow: document.documentElement.scrollWidth > innerWidth || document.querySelector('.rs-keyboard').scrollWidth > kb.width + 1,
                  smallest: Math.min(...keys.map((k) => Math.min(k.width, k.height))),
                  body: r('.rs-body').height};
        }''')
        check('keyboard leaves search field and buttons uncovered', layout['clear'])
        check('keyboard fits 1024x600 without overflow', layout['inside'] and not layout['overflow'] and layout['body'] > 150)
        check('touch keys are at least 44px', layout['smallest'] >= 44)
        key('hide')
        check('hide closes the keyboard', touch.is_hidden('.rs-keyboard'))
        touch.tap('.rs-input')
        check('touching the field reopens the keyboard', touch.is_visible('.rs-keyboard'))
        touch.keyboard.type('!')
        check('hardware typing still writes the field', touch.input_value('.rs-input') == 'Cyberpunk!')
        key('back')
        key('enter')
        touch.wait_for_selector('.rs-article:not([hidden]) h1')
        check('keyboard search runs research and hides keyboard', touch.inner_text('.rs-article h1') == 'Cyberpunk' and touch.is_hidden('.rs-keyboard'))
        check('result shows sources', touch.locator('.rs-sources li').count() > 0)
        touch.tap('.rs-input')
        key('a')
        check('first key replaces the finished query', touch.input_value('.rs-input') == 'a')
        touch.tap('.rs-close')
        check('closing research hides keyboard and returns to gallery', touch.is_hidden('#research') and touch.is_hidden('.rs-keyboard'))
        check('touch keyboard has no console errors', not touch_errors)
        desktop = browser.new_page(viewport={'width': 1280, 'height': 800})
        desktop.goto(base + '?autoplay=0')
        desktop.wait_for_selector('#app[data-state=ready]')
        desktop.press('body', 'r')
        desktop.click('.rs-input')
        check('desktop mouse keeps the system keyboard path', desktop.is_hidden('.rs-keyboard'))
        desktop.close()
        touch.context.close()
        browser.close()
    server.shutdown()
    server.server_close()
    result = {'checks': checks, 'passed': sum(c['pass'] for c in checks), 'total': len(checks), 'paid_calls': 0}
    path = ROOT / 'docs/validation/browser-contract.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('%d/%d checks passed' % (result['passed'], result['total']))
    return 0 if all(c['pass'] for c in checks) else 1


if __name__ == '__main__':
    sys.exit(main())
