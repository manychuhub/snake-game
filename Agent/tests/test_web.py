import base64
from concurrent.futures import ThreadPoolExecutor
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

    def test_common_ai_command_answer_and_confirmed_work_log(self):
        path = '/api/ai/command'
        context = {'view': 'agent', 'rackId': 'R1', 'serverId': 'srv-1', 'serialNumber': 'SN-1',
                   'ticketId': 'TT-100', 'shiftType': '야간조'}
        body = {'message': '/기록 새 점검 기록', 'context': context}
        self.assertEqual(self.request('POST', path, body, {'Cookie': ''})[0], 401)
        self.assertEqual(self.request('POST', path, {'message': '질문', 'context': []})[0], 400)
        code, pending = self.request('POST', path, body)
        self.assertEqual((code, pending['type']), (200, 'pending_confirmation'))
        self.assertEqual(database.get_work_logs(), [])
        self.assertEqual(pending['target'], {key: context[key] for key in
                                             ('rackId', 'serverId', 'serialNumber', 'ticketId')})
        code, action = self.request('POST', '/api/ai/confirm', {
            'confirmationId': pending['confirmationId'], 'approved': True,
        })
        self.assertEqual((code, action['status']), (200, 'executed'))
        log = database.get_work_log_by_id(action['auditLog']['targetId'])
        self.assertEqual((log['raw_text'], log['device_id'], log['ticket_no'], log['operator']),
                         ('새 점검 기록', 'R1 srv-1 SN-1', 'TT-100', 'admin'))
        event = action['auditLog']
        self.assertEqual(set(event), {'timestamp', 'actor', 'command', 'targetId', 'result'})
        self.assertEqual((event['actor'], event['command'], event['targetId'], event['result']),
                         ('admin', 'create_work_log', str(log['id']), 'executed'))

        with patch.object(gemini_client, 'generate_text', return_value='{"type":"answer","reply":"점검 기록입니다."}') as generate:
            self.assertEqual(self.request('POST', path, {'message': '이 티켓의 기록은?', 'context': context}),
                             (200, {'type': 'answer', 'reply': '점검 기록입니다.'}))
        payload = json.loads(generate.call_args.args[1])
        self.assertEqual(payload['context'], context)
        self.assertEqual(payload['sources'][0]['ticket_no'], 'TT-100')

    def test_common_ai_confirmation_is_account_scoped_and_idempotent(self):
        log_id = database.add_work_log({'raw_text': '업무', 'ticket_no': 'TT-100', 'status': '미완료'})
        plan = json.dumps({'type': 'update_work_log_status', 'ticketId': 'TT-100', 'status': '완료'})
        with patch.object(gemini_client, 'generate_text', return_value=plan):
            code, pending = self.request('POST', '/api/ai/command', {'message': '이 티켓 완료 처리',
                                                                    'context': {'ticketId': 'TT-100'}})
        self.assertEqual((code, pending['type']), (200, 'pending_confirmation'))
        self.assertEqual(set(pending), {'type', 'confirmationId', 'summary', 'target', 'changes', 'reply'})
        self.assertTrue(pending['summary'])
        self.assertTrue(pending['reply'])
        self.assertEqual(pending['target'], {'ticketId': 'TT-100'})
        self.assertEqual(pending['changes']['status'], {'from': '미완료', 'to': '완료'})
        self.assertIn('다음 교대 인계', pending['changes']['handoverNote'])
        self.assertEqual(database.get_work_log_by_id(log_id)['status'], '미완료')

        accounts.create_user('admin-two', 'second-admin-password', admin=True)
        other = 'shift_session=' + accounts.login('admin-two', 'second-admin-password')
        path = '/api/ai/confirm'
        body = {'confirmationId': pending['confirmationId'], 'approved': True}
        self.assertEqual(self.request('POST', path, body, {'Cookie': other})[0], 404)
        self.assertEqual(self.request('POST', path, {**body, 'approved': 'true'})[0], 400)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.request, 'POST', path, body)
            second = pool.submit(self.request, 'POST', path, body)
            code, executed = first.result()
            self.assertEqual(second.result(), (code, executed))
        self.assertEqual((code, executed['status']), (200, 'executed'))
        self.assertEqual(executed['auditLog']['actor'], 'admin')
        self.assertEqual(database.get_work_log_by_id(log_id)['status'], '완료')
        self.assertIn(pending['changes']['handoverNote'], database.get_work_log_by_id(log_id)['follow_up'])
        notes = [log for log in database.get_work_logs() if log['incident_type'] == '다음 교대 인계']
        self.assertEqual([note['raw_text'] for note in notes], [pending['changes']['handoverNote']])
        self.assertEqual(sum(row['action'] == 'update_work_log_status' for row in database.get_audit_trails()), 1)

    def test_common_ai_cancellation_and_changed_target(self):
        log_id = database.add_work_log({'ticket_no': 'TT-100', 'status': '미완료'})
        body = {'message': 'TT-100 완료 처리', 'context': {}}
        plan = json.dumps({'type': 'update_work_log_status', 'ticketId': 'TT-100', 'status': '완료'})
        with patch.object(gemini_client, 'generate_text', return_value=plan):
            _, first = self.request('POST', '/api/ai/command', body)
            _, second = self.request('POST', '/api/ai/command', body)
        path = '/api/ai/confirm'
        cancellation = {'confirmationId': first['confirmationId'], 'approved': False}
        code, cancelled = self.request('POST', path, cancellation)
        self.assertEqual((code, cancelled['status']), (200, 'cancelled'))
        self.assertEqual(database.get_work_log_by_id(log_id)['status'], '미완료')
        self.assertEqual(self.request('POST', path, {**cancellation, 'approved': True}), (code, cancelled))
        database.update_work_log(log_id, {'status': '추가점검'})
        code, stale = self.request('POST', path, {'confirmationId': second['confirmationId'], 'approved': True})
        self.assertEqual((code, stale['status'], stale['auditLog']['result']), (200, 'cancelled', 'target_changed'))
        self.assertEqual(database.get_work_log_by_id(log_id)['status'], '추가점검')

    def test_console_launch_route_requires_a_confirmed_request(self):
        inventory = {'racks': {'R1': {}}, 'servers': {'S1': {'rackId': 'R1', 'consoleUrl': 'https://bmc.invalid/'}}}
        plan = json.dumps({'type': 'open_bmc_console', 'serverId': 'S1'})
        with (patch.dict('os.environ', {'SHIFT_BRIDGE_DCO_INVENTORY_JSON': json.dumps(inventory)}),
              patch.object(gemini_client, 'generate_text', return_value=plan)):
            code, pending = self.request('POST', '/api/ai/command', {'message': 'S1 콘솔 열기', 'context': {}})
            self.assertEqual((code, pending['type']), (200, 'pending_confirmation'))
            path = '/api/ai/console/' + pending['confirmationId']
            self.assertEqual(self.request('GET', path)[0], 404)
            self.assertEqual(self.request('GET', path, headers={'Cookie': ''})[0], 401)
            code, result = self.request('POST', '/api/ai/confirm', {'confirmationId': pending['confirmationId'],
                                                                    'approved': True})
            self.assertEqual((code, result['status']), (200, 'executed'))
            self.assertIn(path, result['reply'])
            self.assertEqual(self.request('GET', path)[0], 303)
            self.assertEqual(self.response_headers['Location'], 'https://bmc.invalid/')

    def test_workspace_ai_filters_and_delivers_only_to_the_assigned_account(self):
        accounts.create_user('night-owner', 'synthetic-owner-password')
        cookie = 'shift_session=' + accounts.login('night-owner', 'synthetic-owner-password')
        database.add_work_log({'execution_time': '02:43', 'ticket_no': 'TT-HW-1', 'operator': 'night-owner',
                               'incident_type': 'RAM 오류', 'action_taken': '예비 RAM 교체 예정', 'status': '추가점검'})
        database.add_work_log({'execution_time': '12:43', 'ticket_no': 'TT-DAY-1', 'operator': 'unknown',
                               'incident_type': '광선로', 'action_taken': '광선로 교체 예정'})
        base = '/api/ai/command'
        body = {'message': '야간 장애 티켓 열어', 'context': {'view': 'tab-classify'}}
        self.assertEqual(self.request('POST', base, body)[1]['action']['filter'], 'night_incidents')
        for key in ('night_incidents', 'open_replacements'):
            _, data = self.request('GET', '/api/logs?dco=' + key)
            self.assertEqual([row['ticket_no'] for row in data['logs']], ['TT-HW-1'])
        body['message'] = '미완료 하드웨어 교체 담당자에게 알림 보내'
        _, sent = self.request('POST', base, body)
        self.assertEqual(sent['type'], 'action_executed')
        self.assertEqual(self.request('POST', base, body)[1]['type'], 'answer')
        _, activity = self.request('GET', '/api/ai/activity')
        self.assertEqual(activity['notifications'], [])
        self.assertEqual(activity['auditLogs'][0]['targetId'], 'TT-HW-1')
        _, owner = self.request('GET', '/api/ai/activity', headers={'Cookie': cookie})
        self.assertEqual([entry['ticketId'] for entry in owner['notifications']], ['TT-HW-1'])
        self.assertEqual(owner['auditLogs'], [])

    def test_workspace_media_uses_exact_serial_and_revalidates_approval(self):
        target = {'view': 'media', 'serialNumber': 'SN-42'}
        row = {'ticket_no': 'TT-MEDIA-1', 'device_id': 'RACK-A1 SRV-01 SN:SN-42 PART:SSD',
               'incident_type': '저장 매체 삭제', 'result': '삭제 검증 완료', 'status': '완료'}
        log_id = database.add_work_log(row)
        database.add_work_log({**row, 'ticket_no': 'TT-MEDIA-2', 'device_id': 'SN:SN-420', 'result': '검증 실패'})
        command = '/api/ai/command'
        verify = self.request('POST', command, {'message': '삭제 로그 검증', 'context': target})[1]
        self.assertIn(f'#{log_id}', verify['reply'])
        draft = self.request('POST', command, {'message': '폐기 증적 리포트 초안 생성', 'context': target})[1]
        self.assertIn('SN-42', draft['reply'])
        request = {'message': '폐기 대기 전환', 'context': target}
        pending = self.request('POST', command, request)[1]
        self.assertEqual(pending['target'], {'rackId': 'RACK-A1', 'serverId': 'SRV-01',
                                             'serialNumber': 'SN-42', 'ticketId': 'TT-MEDIA-1'})
        database.update_work_log(log_id, {'result': '증적 재확인 필요'})
        confirm = '/api/ai/confirm'
        outcome = self.request('POST', confirm, {'confirmationId': pending['confirmationId'], 'approved': True})[1]
        self.assertEqual((outcome['status'], outcome['auditLog']['result']), ('cancelled', 'target_changed'))
        database.update_work_log(log_id, {'result': row['result']})
        pending = self.request('POST', command, request)[1]
        body = {'confirmationId': pending['confirmationId'], 'approved': True}
        first = self.request('POST', confirm, body)[1]
        self.assertEqual(first['auditLog']['targetId'], 'SN-42')
        self.assertEqual(self.request('POST', confirm, body)[1], first)
        self.assertEqual(database.get_work_log_by_id(log_id)['status'], '폐기 대기')
        self.assertEqual(self.request('GET', '/api/ai/activity')[1]['auditLogs'][0]['command'], 'queue_media_disposal')

    def test_detail_context_note_and_document_sources_mask_credentials(self):
        log_id = database.add_work_log({'ticket_no': 'TT-OPS-1', 'device_id': 'Hall-A R14 svr-kr-a14-03',
                                       'follow_up': '교체 확인'})
        database.add_technical_doc('HDD 폐기 SOP.md', '삭제 SOP', '매체 삭제 승인 기준', '이중 검증', '예시')
        context = {'view': 'ticket/hdd', 'rackId': 'R14', 'serverId': 'svr-kr-a14-03',
                   'ticketId': 'TT-OPS-1', 'shiftType': '야간조'}
        secret = 'synthetic-confidential-value'
        with patch.object(gemini_client, 'generate_text', return_value=(
                '{"type":"answer","reply":"HDD 폐기 SOP.md\nAPI 키: ' + secret + '"}').replace('\n', '\\n')) as generate:
            code, answer = self.request('POST', '/api/ai/command',
                                        {'message': '저장 매체 삭제 규정', 'context': context})
        self.assertEqual(code, 200)
        self.assertNotIn(secret, answer['reply'])
        prompt = json.loads(generate.call_args.args[1])
        self.assertEqual(prompt['context'], context)
        self.assertIn('HDD 폐기 SOP.md', [item.get('filename') for item in prompt['sources']])
        _, pending = self.request('POST', '/api/ai/command',
                                  {'message': '인계 노트 추가: 전원 확인 비밀번호=' + secret, 'context': context})
        self.assertEqual((pending['type'], pending['target']['rackId']), ('pending_confirmation', 'R14'))
        self.assertNotIn(secret, str(pending))
        self.assertEqual(database.get_work_log_by_id(log_id)['follow_up'], '교체 확인')
        self.request('POST', '/api/ai/confirm', {'confirmationId': pending['confirmationId'], 'approved': True})
        follow_up = database.get_work_log_by_id(log_id)['follow_up']
        self.assertIn('교체 확인\n[admin] 전원 확인', follow_up)
        self.assertNotIn(secret, follow_up)

    def test_workspace_console_link_requires_confirming_account(self):
        settings = {'racks': {'RACK-1': {}}, 'servers': {'SRV-01': {
            'rackId': 'RACK-1', 'consoleUrl': 'https://bmc.example.invalid/console'}}}
        with patch.dict('os.environ', {'SHIFT_BRIDGE_DCO_INVENTORY_JSON': json.dumps(settings)}):
            _, pending = self.request('POST', '/api/ai/command',
                                      {'message': 'IPMI 콘솔 열어', 'context': {'view': 'server', 'serverId': 'SRV-01'}})
            self.assertEqual(pending['type'], 'pending_confirmation')
            path = '/api/ai/console/' + pending['confirmationId']
            self.assertEqual(self.request('GET', path)[0], 404)
            _, confirmed = self.request('POST', '/api/ai/confirm',
                                        {'confirmationId': pending['confirmationId'], 'approved': True})
            self.assertIn(path, confirmed['reply'])
            self.assertEqual(self.request('GET', path)[0], 303)
            self.assertEqual(self.response_headers['Location'], 'https://bmc.example.invalid/console')

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
