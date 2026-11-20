import base64
import http.client
from io import BytesIO
import json
from pathlib import Path
import tempfile
from threading import Thread
import time
import unittest
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

import accounts
import alb_identity
import app
import database
import gemini_client


class WebTests(unittest.TestCase):
    def setUp(self):
        state = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(database, 'DB_PATH', Path(state) / 'test.db'))
        self.enterContext(patch.dict('os.environ', {'SHIFT_BRIDGE_SEED_DEMO': '0'}))
        database.init_db()
        accounts.init()
        accounts.create_user('admin', 'test-admin-password', admin=True)
        self.cookie = 'shift_session=' + accounts.login('admin', 'test-admin-password')
        self.server = app.ThreadingTCPServer(('127.0.0.1', 0), app.ShiftBridgeHandler)
        self.addCleanup(self.server.server_close)
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        self.addCleanup(connection.close)
        connection.request(method, path, body=json.dumps(body) if body is not None else None,
                           headers={'Content-Type': 'application/json', 'Cookie': self.cookie, **(headers or {})})
        response = connection.getresponse()
        self.response_headers = response.headers
        body = response.read()
        if body and response.headers.get_content_type() == 'application/json':
            return response.status, json.loads(body)
        return response.status, body.decode('utf-8')

    def test_cloud_requires_identity_and_same_origin(self):
        origin = 'https://shift.example.com'
        with (patch.object(app, 'EXPECTED_SIGNER', 'example-alb'),
              patch.object(app, 'PUBLIC_ORIGIN', origin),
              patch.object(app, 'verified_subject', return_value=None, create=True) as verify):
            self.assertEqual(self.request('GET', '/healthz')[0], 200)
            self.assertEqual(self.request('GET', '/api/logs')[0], 401)
            self.assertEqual(self.request('GET', '/about')[0], 401)
            verify.return_value = 'authenticated-user-id'
            self.assertEqual(self.request('POST', '/api/logs/delete', {'id': 1}, {'Origin': 'https://other.example'})[0], 403)
            self.assertEqual(self.request('POST', '/api/logs/delete', [], {'Origin': origin})[0], 400)
            self.assertEqual(self.request('GET', '/api/logs'), (200, {'logs': []}))

    def test_approval_keeps_verified_identity_and_runs_once(self):
        origin = 'https://shift.example.com'
        report_id = database.save_handover_report({'raw_markdown': '초안'})
        with (patch.object(app, 'EXPECTED_SIGNER', 'example-alb'),
              patch.object(app, 'PUBLIC_ORIGIN', origin),
              patch.object(app, 'verified_subject', return_value='verified-user', create=True)):
            body = {'id': report_id, 'approver_name': '값 위조', 'edited_markdown': '승인본'}
            status, data = self.request('POST', '/api/reports/approve', body, {'Origin': origin})
            self.assertEqual((status, data['approved_by']), (200, 'admin'))
            self.assertEqual(self.request('POST', '/api/reports/approve', body, {'Origin': origin})[0], 409)
        report = database.get_handover_reports()[0]
        self.assertEqual((report['approved_by'], report['raw_markdown']), ('admin', '승인본'))
        self.assertEqual(database.get_audit_trails()[0]['operator'], 'admin')

    def test_gemini_failure_leaves_no_empty_report(self):
        self.assertEqual(self.request('POST', '/api/logs/create', {'raw_text': 'demo', 'status': '완료'})[0], 200)
        with patch.object(gemini_client, 'generate_text', side_effect=gemini_client.BridgeError('unavailable')):
            self.assertEqual(self.request('POST', '/api/reports/generate', {'shift_start': '2000-01-01T00:00:00Z', 'shift_end': '2099-01-01T00:00:00Z'})[0], 502)
        self.assertEqual(database.get_handover_reports(), [])

    def test_local_web_rejects_untrusted_host(self):
        self.assertEqual(self.request('GET', '/api/logs', headers={'Host': 'other.example'})[0], 403)

    def test_render_publishes_intro_and_authenticates_workspace_and_api(self):
        origin = 'https://shift-example.onrender.com'
        with (patch.object(app, 'EXPECTED_SIGNER', None),
              patch.object(app, 'ON_RENDER', True),
              patch.object(app, 'WEB_USER', None),
              patch.object(app, 'WEB_CREDENTIAL', None),
              patch.object(app, 'PUBLIC_ORIGIN', origin)):
            self.assertEqual(self.request('GET', '/healthz')[0], 200)
            status, page = self.request('GET', '/')
            self.assertEqual(status, 200)
            self.assertIn('에이전트 소개 · SHIFT BRIDGE', page)
            for public_path in ('/about', '/about/', '/about.html', '/about.css', '/about.js',
                                '/demo', '/demo/', '/app.js', '/style.css'):
                self.assertEqual(self.request('GET', public_path)[0], 200, public_path)
                self.assertEqual(self.request('HEAD', public_path)[0], 200, public_path)
            guest = {'Cookie': ''}
            for protected_path in ('/workspace', '/workspace/', '/index.html'):
                self.assertEqual(self.request('GET', protected_path, headers=guest)[0], 303, protected_path)
                self.assertEqual(self.request('HEAD', protected_path, headers=guest)[0], 303, protected_path)
            self.assertEqual(self.request('GET', '/api/logs', headers=guest)[0], 401)
            self.assertEqual(self.request('POST', '/api/logs/create', {'raw_text': 'demo'}, guest)[0], 401)
            database.add_work_log({'raw_text': 'private workspace fixture', 'ticket_no': 'PRIVATE-123'})
            status, demo = self.request('GET', '/demo/api/logs?status=%EB%AF%B8%EC%99%84%EB%A3%8C')
            self.assertEqual((status, [log['ticket_no'] for log in demo['logs']]), (200, ['DEMO-002']))
            self.assertEqual(self.request('GET', '/demo/api/reports')[0], 200)
            self.assertEqual(self.request('GET', '/demo/api/settings/status')[0], 404)
            self.assertEqual(self.request('POST', '/demo/api/logs', {'raw_text': 'demo'}, guest)[0], 401)
            auth = {'Cookie': self.cookie}
            workspace_status, workspace = self.request('GET', '/workspace', headers=auth)
            self.assertEqual(workspace_status, 200)
            self.assertIn('id="rawLogInput"', workspace)
            status, data = self.request('GET', '/api/settings/status', headers=auth)
            self.assertEqual((status, data['signed_in_as']), (200, 'admin'))
            self.assertEqual(self.request('POST', '/api/logs/delete', {'id': 1}, auth)[0], 403)
            self.assertEqual(self.request('POST', '/api/not-found', {}, {**auth, 'Origin': origin})[0], 404)

    def test_shift_report_excludes_resolved_prior_work_and_future_records(self):
        records = [('prior-done', '완료', '2026-01-01 00:00:00'),
                   ('prior-open', '미완료', '2026-01-01 01:00:00'),
                   ('current-done', '완료', '2026-01-01 02:00:00'),
                   ('future-open', '미완료', '2026-01-01 03:00:00')]
        for ticket, status, created in records:
            log_id = database.add_work_log({'ticket_no': ticket, 'status': status})
            with database.get_connection() as connection:
                connection.execute('UPDATE work_logs SET created_at = ? WHERE id = ?', (created, log_id))

        with patch.object(gemini_client, 'generate_handover_report_content', return_value='draft') as generate:
            body = {'shift_start': '2026-01-01T11:00:00+09:00', 'shift_end': '2026-01-01T12:00:00+09:00'}
            self.assertEqual(self.request('POST', '/api/reports/generate', body)[0], 200)
            self.assertEqual([row['ticket_no'] for row in generate.call_args.args[0]], ['current-done', 'prior-open'])


    def test_signup_role_isolation_and_generation_quota(self):
        member = {'username': 'visitor', 'password': 'visitor-password', 'admin': True}
        guest = {'Cookie': ''}
        self.assertEqual(self.request('POST', '/api/account/signup', member, guest)[0], 201)
        self.assertEqual(self.request('POST', '/api/account/login', {**member, 'password': 'wrong'}, guest)[0], 401)
        self.assertEqual(self.request('POST', '/api/account/login', member, guest)[0], 200)
        self.assertIn('HttpOnly', self.response_headers['Set-Cookie'])
        cookie = self.response_headers['Set-Cookie'].split(';')[0]
        visitor = {'Cookie': cookie}
        self.assertEqual(self.request('GET', '/api/admin/login', headers=visitor)[0], 403)
        self.assertEqual(self.request('GET', '/api/settings/status', headers=visitor)[0], 403)
        self.assertEqual(self.request('POST', '/api/settings/test', {}, visitor)[0], 403)
        database.add_work_log({'raw_text': 'admin fixture'})
        self.assertEqual(self.request('GET', '/api/logs', headers=visitor), (200, {'logs': []}))
        payload = {'text': 'fixture'}
        response = Mock()
        with (patch.dict('os.environ', {'SHIFT_BRIDGE_ENGINE_URL': 'http://example.invalid',
                                        'HYBRID_API_AUTH_TOKEN': 'test-token'}),
              patch.object(gemini_client.bridge_opener, 'open', return_value=response) as upstream,
              patch.object(gemini_client, 'translate_handover_report',
                           side_effect=lambda *_: gemini_client.call_gemini_raw({}) and {'translated_text': 'fixture'})):
            for _ in range(3):
                self.assertEqual(self.request('POST', '/api/translate', payload, visitor)[0], 200)
            self.assertEqual(self.request('POST', '/api/translate', payload, visitor)[0], 429)
            self.assertEqual(upstream.call_count, 3)
            self.assertEqual(self.request('GET', '/api/account/me', headers=visitor)[1]['remaining'], 0)
            users = self.request('GET', '/api/admin/members')[1]['users']
            user_id = users[0]['id']
            for enabled, expected in [(True, 200), (False, 429)]:
                self.assertEqual(self.request('POST', '/api/admin/whitelist',
                                              {'user_id': user_id, 'enabled': enabled})[0], 200)
                self.assertEqual(self.request('POST', '/api/translate', payload, visitor)[0], expected)
        self.assertEqual(self.request('GET', '/api/admin/login')[1]['events'][0]['result'], 'success')
        visitor_logins = self.request('GET', '/api/admin/login?q=VISIT')[1]['events']
        self.assertEqual([(event['username'], event['result']) for event in visitor_logins],
                         [('visitor', 'success'), ('visitor', 'failed')])
        self.assertEqual(self.request('GET', '/api/admin/ai')[1]['events'][0]['result'], 'limited')
        self.assertEqual(self.request('GET', '/api/admin/feature')[1]['events'][0]['result'], '429')
        with patch.object(accounts, 'today', return_value='2099-01-01'):
            self.assertEqual(self.request('GET', '/api/account/me', headers=visitor)[1]['remaining'], 3)
        self.assertEqual(self.request('POST', '/api/account/logout', {}, visitor)[0], 200)
        self.assertEqual(self.request('GET', '/api/account/me', headers=visitor)[0], 401)

    def test_admin_password_reset_revokes_only_the_selected_admins_sessions(self):
        accounts.create_user('another-admin', 'another-password', admin=True)
        other = {'Cookie': 'shift_session=' + accounts.login('another-admin', 'another-password')}
        accounts.reset_admin_password('admin', 'replacement-password')
        self.assertEqual(self.request('GET', '/api/admin/login')[0], 401)
        self.assertEqual(self.request('GET', '/api/admin/login', headers=other)[0], 200)
        self.assertIsNone(accounts.login('admin', 'test-admin-password'))
        self.cookie = 'shift_session=' + accounts.login('admin', 'replacement-password')
        status, page = self.request('GET', '/admin')
        self.assertEqual(status, 200)
        self.assertIn('AI 생성 테스트', page)

    def test_account_password_change_checks_identity_and_survives_redeploy(self):
        path = '/api/account/password'
        old = 'test-admin-password'
        new = 'changed-admin-password'
        accounts.bootstrap_admin('admin', old, update_password=True)
        second = {'Cookie': 'shift_session=' + accounts.login('admin', old)}
        user = self.request('GET', '/api/account/preferences')[1]
        body = {'account_id': user['account_id'], 'current_password': old, 'new_password': new}
        self.assertEqual(self.request('POST', path, body, {'Cookie': ''})[0], 401)
        self.assertEqual(self.request('POST', path, {**body, 'account_id': 'unknown'})[0], 409)
        self.assertEqual(self.request('POST', path, {**body, 'current_password': 'wrong'})[0], 400)
        self.assertEqual(self.request('POST', path, {**body, 'new_password': old})[0], 400)
        self.assertEqual(self.request('POST', path, body, {'Origin': 'https://other.example'})[0], 403)
        self.assertEqual(self.request('POST', path, body)[0], 200)
        self.assertIn('Max-Age=0', self.response_headers['Set-Cookie'])
        self.assertEqual(self.request('GET', '/api/account/me')[0], 401)
        self.assertEqual(self.request('GET', '/api/account/me', headers=second)[0], 401)
        accounts.bootstrap_admin('admin', old, update_password=True)
        self.assertIsNone(accounts.login('admin', old))
        self.assertIsNotNone(accounts.login('admin', new))
        accounts.bootstrap_admin('admin', 'rotated-environment-password', update_password=True)
        self.assertIsNone(accounts.login('admin', new))
        self.assertIsNotNone(accounts.login('admin', 'rotated-environment-password'))

    def test_withdrawal_requires_confirmation_and_preserves_work_and_last_admin(self):
        path = '/api/account/delete'
        admin_id = self.request('GET', '/api/account/preferences')[1]['account_id']
        self.assertEqual(self.request('POST', path, {
            'account_id': admin_id, 'current_password': 'test-admin-password', 'confirmed': True})[0], 409)

        username, password = 'retiring-member', 'retiring-member-password'
        accounts.create_user(username, password)
        member = {'Cookie': 'shift_session=' + accounts.login(username, password)}
        data = self.request('GET', '/api/account/preferences', headers=member)[1]
        self.assertEqual(self.request('POST', '/api/account/preferences', {
            'account_id': data['account_id'], 'default_location': '테스트 장소', 'place_type': '사무실'}, member)[0], 200)
        self.assertEqual(self.request('POST', '/api/logs/create', {
            'raw_text': 'member work record', 'status': '완료'}, member)[0], 200)

        accounts.grant_admin(username, password)
        self.assertEqual(self.request('GET', '/api/account/me', headers=member)[0], 401)
        member = {'Cookie': 'shift_session=' + accounts.login(username, password)}
        other_session = {'Cookie': 'shift_session=' + accounts.login(username, password)}
        self.assertEqual(self.request('GET', '/api/admin/login', headers=member)[0], 200)
        self.assertEqual(self.request('GET', '/api/logs', headers=member)[1]['logs'][0]['raw_text'], 'member work record')
        body = {'account_id': data['account_id'], 'current_password': password}
        self.assertEqual(self.request('POST', path, body, member)[0], 400)
        self.assertEqual(self.request('POST', path, {**body, 'confirmed': True, 'current_password': 'wrong'}, member)[0], 400)
        self.assertEqual(self.request('POST', path, {**body, 'confirmed': True}, member)[0], 200)
        self.assertIn('Max-Age=0', self.response_headers['Set-Cookie'])
        self.assertEqual(self.request('GET', '/api/account/me', headers=other_session)[0], 401)
        self.assertEqual(self.request('GET', '/api/admin/login')[0], 200)
        accounts.bootstrap_admin(username, password, update_password=True)
        self.assertIsNone(accounts.login(username, password))
        with self.assertRaises(ValueError):
            accounts.create_user(username, password)
        with database.get_connection() as conn:
            user = conn.execute('SELECT retired,password FROM web_users WHERE username=?', (username,)).fetchone()
            self.assertEqual(tuple(user), (1, ''))
            self.assertIsNone(conn.execute('SELECT 1 FROM web_preferences WHERE user_id=?', (data['account_id'],)).fetchone())
        with database.get_connection(accounts.workspace_path(data['account_id'])) as conn:
            self.assertEqual(conn.execute('SELECT raw_text FROM work_logs').fetchone()[0], 'member work record')

    def test_place_preferences_are_private_to_the_signed_in_account(self):
        path = '/api/account/preferences'
        guest = {'Cookie': ''}
        self.assertEqual(self.request('GET', path, headers=guest)[0], 401)
        self.assertEqual(self.request('POST', path, {}, guest)[0], 401)
        self.assertEqual(self.request('GET', '/account/preferences', headers=guest)[0], 303)
        self.assertIn('id="preferences"', self.request('GET', '/admin')[1])

        status, account_a = self.request('GET', path)
        self.assertEqual(status, 200)
        self.assertEqual(self.response_headers['Cache-Control'], 'no-store')
        self.assertEqual((account_a['default_location'], account_a['place_type']), ('', ''))
        values_a = {'account_id': account_a['account_id'], 'default_location': ' A 기본 위치 ',
                    'place_type': '데이터센터'}
        self.assertEqual(self.request('POST', path, values_a)[0], 200)
        old_admin = {'Cookie': self.cookie}

        member = {'username': 'preferences-member', 'password': 'fixture-member-password'}
        self.assertEqual(self.request('POST', '/api/account/signup', member, guest)[0], 201)
        self.assertEqual(self.request('POST', '/api/account/login', member, old_admin)[0], 200)
        member_cookie = self.response_headers['Set-Cookie'].split(';')[0]
        switched = {'Cookie': member_cookie}
        self.assertEqual(self.request('GET', path, headers=old_admin)[0], 401)
        self.assertEqual(self.request('GET', '/admin', headers=switched)[0], 403)
        self.assertIn('id="preferences"', self.request('GET', '/account/preferences', headers=switched)[1])

        status, account_b = self.request('GET', path + '?user_id=' + account_a['account_id'], headers=switched)
        self.assertEqual(status, 200)
        self.assertNotEqual(account_a['account_id'], account_b['account_id'])
        self.assertEqual((account_b['default_location'], account_b['place_type']), ('', ''))
        self.assertEqual(self.request('POST', path, values_a, switched)[0], 409)
        values_b = {'account_id': account_b['account_id'], 'default_location': 'B 기본 위치', 'place_type': '사무실'}
        self.assertEqual(self.request('POST', path, {**values_b, 'place_type': 42}, switched)[0], 400)
        self.assertEqual(self.request('POST', path, values_b, {**switched, 'Origin': 'https://other.example'})[0], 403)
        self.assertEqual(self.request('POST', path, {**values_b, 'user_id': account_a['account_id']}, switched)[0], 200)
        stored_b = self.request('GET', path, headers=switched)[1]
        self.assertEqual({key: stored_b[key] for key in values_b}, values_b)
        self.assertEqual(self.request('POST', '/api/account/logout', {}, switched)[0], 200)
        self.assertEqual(self.request('GET', path, headers=switched)[0], 401)
        self.assertEqual(self.request('POST', path, values_b, switched)[0], 401)
        self.assertIsNone(accounts.save_preferences(int(account_b['account_id']), member_cookie.split('=', 1)[1], values_b))

        self.assertEqual(self.request('POST', '/api/account/login',
                                      {'username': 'admin', 'password': 'test-admin-password'}, guest)[0], 200)
        self.cookie = self.response_headers['Set-Cookie'].split(';')[0]
        stored_a = self.request('GET', path)[1]
        self.assertEqual((stored_a['default_location'], stored_a['place_type']), ('A 기본 위치', '데이터센터'))
        self.assertEqual(self.request('POST', path, {**values_a, 'default_location': ''})[0], 200)
        cleared_a = self.request('GET', path)[1]
        self.assertEqual((cleared_a['default_location'], cleared_a['place_type']), ('', '데이터센터'))

    def test_admin_gemini_connection_test_is_logged(self):
        payload = b'{"candidates":[{"content":{"parts":[{"text":"OK"}]}}]}'
        health = {'auth_configured': True, 'api_key_configured': True}
        engine = {'SHIFT_BRIDGE_ENGINE_URL': 'http://example.invalid', 'HYBRID_API_AUTH_TOKEN': 'test-token'}
        with (patch.dict('os.environ', engine), patch.object(gemini_client, 'get_bridge_health', return_value=health),
              patch.object(gemini_client.bridge_opener, 'open', return_value=BytesIO(payload))):
            self.assertTrue(self.request('GET', '/api/settings/status')[1]['api_key_configured'])
            status, data = self.request('POST', '/api/settings/test', {})
        self.assertEqual((status, data['success'], data['reply_sample']), (200, True, 'OK'))
        event = self.request('GET', '/api/admin/ai?q=admin')[1]['events'][0]
        self.assertEqual((event['feature'], event['result']), ('/api/settings/test', 'success'))


class AlbAssertionTests(unittest.TestCase):
    def test_signed_identity_rejects_wrong_signer_expired_and_tampered_data(self):
        key = ec.generate_private_key(ec.SECP256R1())
        signer = 'arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:loadbalancer/app/test/abc'
        headers = {'alg': 'ES256', 'kid': '12345678-1234-1234-1234-123456789000', 'signer': signer}

        def encode(value):
            return base64.urlsafe_b64encode(json.dumps(value).encode()).decode()

        def assertion(exp):
            content = f"{encode(dict(headers, exp=exp))}.{encode({'sub': 'user'})}"
            r, s = utils.decode_dss_signature(key.sign(content.encode(), ec.ECDSA(hashes.SHA256())))
            signature = base64.urlsafe_b64encode(r.to_bytes(32, 'big') + s.to_bytes(32, 'big')).decode()
            return f'{content}.{signature}'

        with patch.object(alb_identity, 'signing_key', return_value=key.public_key()):
            valid = assertion(time.time() + 60)
            header, _, signature = valid.split('.')
            self.assertEqual(alb_identity.verified_subject(valid, signer), 'user')
            self.assertIsNone(alb_identity.verified_subject(valid, signer + 'different'))
            self.assertIsNone(alb_identity.verified_subject(assertion(time.time() - 60), signer))
            self.assertIsNone(alb_identity.verified_subject(f"{header}.{encode({'sub': 'different'})}.{signature}", signer))
