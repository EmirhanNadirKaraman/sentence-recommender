"""Authorization must run before expensive viewers, over real HTTP."""
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock, patch

from web import render
from web.access import OWNER_ACTIONS, OWNER_PAGES
from web.server import _make_handler


class SharingTest(unittest.TestCase):
    def setUp(self):
        self.door = Mock(shared=True, google=None)
        self.door.registry.session.side_effect = lambda token: SimpleNamespace(name=token)
        self.door.is_owner.side_effect = lambda reader: reader.name == 'owner'
        self.viewer = Mock()
        for method in ('frontier', 'blocked', 'cover_page', 'fix', 'next_up'):
            getattr(self.viewer, method).return_value = '<p>ready</p>'
        self.door.viewers.return_value.pick.return_value = self.viewer
        self.door.building.return_value = __import__('contextlib').nullcontext()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), _make_handler(self.door))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, who='friend', body=''):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        connection.request(method, path, body, {'Cookie': f'i1_session={who}'})
        response = connection.getresponse()
        result = response.status, response.read().decode()
        connection.close()
        return result

    def test_local_invitation_uses_configured_public_url(self):
        self.door.registry.owner.return_value = SimpleNamespace(name='owner')
        self.door.registry.invite.return_value = 'test-token'
        with patch.dict('os.environ', {'PUBLIC_URL': 'https://public.example.test/'}), \
                patch('web.render.invited_page', side_effect=lambda url, found: url):
            status, body = self.request('POST', '/invite', 'owner', 'language=de&native=en')
        self.assertEqual(status, 200)
        self.assertEqual(body, 'https://public.example.test/signup?invite=test-token')

    def test_friend_cannot_bypass_hidden_pages_or_actions(self):
        for method, paths in [('GET', OWNER_PAGES), ('POST', OWNER_ACTIONS)]:
            for path in paths:
                with self.subTest(method=method, path=path):
                    status, body = self.request(method, path + '/?list=other')
                    self.assertEqual(status, 403)
                    if path.startswith('/api/'):
                        self.assertEqual(json.loads(body), {'error': 'owner only'})
        self.door.viewers.assert_not_called()
        self.door.building.assert_not_called()

    def test_large_body_is_refused_before_reading_or_running_work(self):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        connection.request('POST', '/known', headers={'Content-Length': str(1024 * 1024 + 1)})
        response = connection.getresponse()
        self.assertEqual(response.status, 413)
        response.read()
        connection.close()
        self.door.viewers.assert_not_called()

    def test_owner_can_still_open_heavy_pages(self):
        for path in OWNER_PAGES - {'/api/cover-search'}:
            with self.subTest(path=path):
                self.assertEqual(self.request('GET', path, 'owner'), (200, '<p>ready</p>'))

    def test_friend_can_read(self):
        self.assertEqual(self.request('GET', '/'), (200, '<p>ready</p>'))
        self.viewer.next_up.assert_called_once()

    def test_health_check_needs_neither_session_nor_corpus(self):
        self.assertEqual(self.request('GET', '/healthz'), (200, '{"status": "ok"}'))
        self.door.viewers.assert_not_called()

    def test_deployment_closes_uninvited_signup_even_with_google(self):
        self.door.google = object()
        with patch.dict('os.environ', {'INVITE_ONLY': '1'}):
            self.assertEqual(self.request('GET', '/signup')[0], 403)


class NavigationAccessTest(unittest.TestCase):
    def test_mobile_and_desktop_hide_owner_pages_for_friends(self):
        before = render.ACTIVE.__dict__.copy()
        try:
            for owner in (False, True):
                render.ACTIVE.owner = owner
                page = render.layout('Home', '<p>hello</p>')
                for path in OWNER_PAGES - {'/api/cover-search', '/fix'}:
                    with self.subTest(owner=owner, path=path):
                        self.assertEqual(f'href="{path}"' in page, owner)
                self.assertIn('href="/reels"', page)
                from web.handlers import Viewer
                tools = Viewer._sentence_tools('Hallo', 'subtitle', '/')
                self.assertEqual("href='/fix?" in tools, owner)
        finally:
            render.ACTIVE.__dict__.clear()
            render.ACTIVE.__dict__.update(before)

    def test_hosting_refuses_an_installation_without_owner_auth(self):
        from web.server import LocalServer
        door = Mock()
        door.registry.owner.return_value = None
        with patch('web.server.Door', return_value=door), \
                patch.dict('os.environ', {'REQUIRE_AUTH': '1'}):
            with self.assertRaisesRegex(SystemExit, 'register an owner'):
                LocalServer(Mock())
