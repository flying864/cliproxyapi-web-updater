#!/usr/bin/env python3
"""Optional real Chromium UI regression, using the compiled plugin's HTML.

Test-only dependency: playwright + its Chromium browser. All HTTP is intercepted;
status values are explicit fixtures, never a claim about a deployed service.
Screenshots land in ignored test-output/panel-browser/.
"""
import base64
import json
from pathlib import Path
import sys
import time
import unittest

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_plugin


ORIGIN = 'http://cpa-panel.test'
PANEL = '/v0/resource/plugins/cpa-updater/panel'
READY = dict(protocol=1, state='ready', current='v8.0.55', latest='v8.0.56',
             detail='测试环境：发现官方正式版，等待管理员确认。',
             updated_at='2026-11-07T08:00:00Z', pending=False)


class PanelBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_plugin.Regression.setUpClass()
        fixture = test_plugin.Regression()
        result = fixture.invoke('management.handle', {'Method': 'GET', 'Path': PANEL})['result']
        cls.html = base64.b64decode(result['Body']).decode()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()
        cls.output = ROOT / 'test-output/panel-browser'
        cls.output.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        test_plugin.Regression.tearDownClass()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 960})
        self.page = self.context.new_page()
        self.errors = []
        self.posts = []
        self.status = dict(READY)
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.context.route('**/*', self.respond)

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def respond(self, route):
        url = route.request.url
        if url == ORIGIN + PANEL:
            route.fulfill(content_type='text/html', body=self.html)
        elif url == ORIGIN + '/embedded':
            route.fulfill(content_type='text/html', body=(
                "<!doctype html><title>Test host (not the official management UI)</title>"
                "<iframe title='Plugin' style='width:100%;height:900px;border:0' src='" + PANEL + "'></iframe>"))
        elif '/v0/management/plugins/cpa-updater/' in url:
            self.assertEqual(route.request.headers.get('authorization'), 'Bearer browser-test-only')
            if route.request.method == 'POST':
                self.posts.append(url)
                self.status = {**READY, 'state': 'checking', 'detail': '测试环境：正在检查'}
                route.fulfill(status=202, content_type='application/json', body='{"message":"queued"}')
            else:
                time.sleep(0.15)  # expose visual state during a realistic network round trip
                route.fulfill(content_type='application/json', body=json.dumps(self.status))
        else:
            route.abort()

    def test_first_paint_without_click_standalone_and_iframe(self):
        for embedded in [False, True]:
            self.page.goto(ORIGIN + ('/embedded' if embedded else PANEL))
            target = self.page.frame_locator('iframe') if embedded else self.page
            self.assertTrue(target.locator('h1').is_visible())
            self.assertTrue(target.locator('#key').is_visible())
            self.assertTrue(target.locator('#check').is_visible())
            self.assertEqual(target.locator('#current').inner_text(), '—')
            self.assertTrue(target.locator('#check').is_disabled())

    def test_late_key_value_connects_without_click_or_input_event(self):
        # Reproduce a password manager/form restore updating .value silently.
        # This is not Chromium's protected password-preview implementation.
        for embedded in [False, True]:
            with self.subTest(embedded=embedded):
                self.page.goto(ORIGIN + ('/embedded' if embedded else PANEL))
                target = self.page.frame_locator('iframe') if embedded else self.page
                target.locator('#key').evaluate("node => { node.value = 'browser-test-only'; }")
                self.page.wait_for_timeout(2800)
                self.assertEqual(target.locator('#current').inner_text(), READY['current'],
                                 'silent restored key must connect without clicking')
                self.assertEqual(target.locator('#connection').inner_text(), '已连接')
                self.assertEqual(self.posts, [], 'opening the panel may only read status')

    def test_idle_poll_does_not_toggle_buttons(self):
        self.page.goto(ORIGIN + PANEL)
        self.page.locator('#key').fill('browser-test-only')
        self.page.wait_for_function("!document.getElementById('check').disabled")
        self.page.evaluate("""() => {
          window.disabledChanges = [];
          new MutationObserver(records => {
            for (const r of records) if (r.oldValue !== r.target.getAttribute('disabled'))
              window.disabledChanges.push(r.target.id);
          }).observe(document.querySelector('.actions'),
            {subtree:true, attributes:true, attributeFilter:['disabled'], attributeOldValue:true});
        }""")
        self.page.wait_for_timeout(4500)
        self.assertEqual(self.page.evaluate('window.disabledChanges'), [], 'idle polling must not flash disabled controls')
        self.page.locator('#check').click()
        self.page.wait_for_function("document.getElementById('check').disabled")
        self.assertEqual(len(self.posts), 1)

    def test_click_during_held_poll_and_state_veto(self):
        self.page.on('dialog', lambda dialog: dialog.accept())
        for next_state in ['ready', 'current']:
            with self.subTest(next_state=next_state):
                self.posts.clear()
                self.status = dict(READY)
                self.page.goto(ORIGIN + PANEL)
                self.page.locator('#key').fill('browser-test-only')
                self.page.wait_for_function("!document.getElementById('update').disabled")
                held = []
                pattern = '**/v0/management/plugins/cpa-updater/status'
                self.page.route(pattern, lambda route: held.append(route))
                try:
                    with self.page.expect_request(lambda request: request.url.endswith('/status')):
                        self.page.wait_for_timeout(2300)
                    self.assertEqual(len(held), 1)
                    self.assertTrue(self.page.locator('#update').is_enabled())
                    self.page.locator('#update').click()
                    self.assertTrue(self.page.locator('#update').is_disabled())
                    self.assertEqual(self.posts, [], 'POST must wait for held GET')
                    held.pop().fulfill(content_type='application/json',
                                       body=json.dumps({**READY, 'state': next_state}))
                    if next_state == 'ready':
                        self.page.wait_for_function("document.getElementById('connection').textContent.includes('请求已提交')")
                        self.assertEqual(len(self.posts), 1)
                        self.assertTrue(self.posts[0].endswith('/update?version=v8.0.56'))
                    else:
                        self.page.wait_for_function("document.getElementById('connection').textContent.includes('未提交')")
                        self.assertEqual(self.posts, [])
                finally:
                    self.page.unroute(pattern)

    def test_responsive_themes_and_safe_links(self):
        for scheme, width in [('light', 1280), ('dark', 1280), ('light', 390), ('dark', 390), ('light', 320)]:
            with self.subTest(scheme=scheme, width=width):
                self.page.emulate_media(color_scheme=scheme, reduced_motion='reduce')
                self.page.set_viewport_size({'width': width, 'height': 960})
                self.page.goto(ORIGIN + PANEL)
                self.page.locator('#key').fill('browser-test-only')
                self.page.wait_for_function("!document.getElementById('check').disabled")
                self.assertEqual(self.page.locator('#current').inner_text(), READY['current'])
                self.assertEqual(self.page.locator('#release').get_attribute('href'),
                                 'https://github.com/router-for-me/CLIProxyAPI/releases/tag/v8.0.56')
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                self.assertEqual(self.page.evaluate('localStorage.length + sessionStorage.length'), 0)
                self.page.screenshot(path=str(self.output / f'{scheme}-{width}.png'), full_page=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
