import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import ai_commands as ai
import database as db
import dco_tools as dco


class DcoToolTests(unittest.TestCase):
    admin = {'id': 1, 'username': 'operator', 'admin': True}
    other_admin = {'id': 2, 'username': 'other-operator', 'admin': True}
    member = {'id': 3, 'username': 'member', 'admin': False}
    target = {'rackId': 'RACK-01', 'serverId': 'SRV-01', 'serialNumber': 'SN-9921'}

    def setUp(self):
        self.path = Path(self.enterContext(TemporaryDirectory()))
        self.inventory = {
            'racks': {'RACK-01': {'switches': {'3': ['9', '10']}}},
            'servers': {'SRV-01': {'rackId': 'RACK-01', 'serialNumbers': ['SN-9921'],
                                   'consoleUrl': 'https://fixture.invalid/console'}},
            'hdd': {'HDD-4TB': 1},
        }
        self.enterContext(patch.object(db, 'DB_PATH', self.path / 'test.db'))
        self.enterContext(patch.dict(os.environ, {'SHIFT_BRIDGE_DATABASE_URL': '',
                                                  'SHIFT_BRIDGE_DCO_INVENTORY_JSON': json.dumps(self.inventory)}))
        db.init_db(seed=False)

    def command(self, message, tool, *, context=None, member=None, **arguments):
        with patch.object(ai.gemini, 'generate_text', return_value=json.dumps({'type': tool, **arguments})):
            return ai.command({'message': message, 'context': context or {}}, member or self.admin)

    def confirm(self, pending, *, approved=True, member=None):
        return ai.confirm({'confirmationId': pending['confirmationId'], 'approved': approved},
                          member or self.admin)

    def test_navigation_and_read_only_script_validate_arguments_and_hide_process_output(self):
        script = self.path / 'read_link.py'
        script.write_text(
            'import json, os, sys\n'
            'assert sys.argv[1:3] == ["RACK-01", "3"]\n'
            'assert "HYBRID_API_AUTH_TOKEN" not in os.environ\n'
            'if sys.argv[3] == "--all":\n'
            '    print(json.dumps({"ports": {"9": "up", "11": "up"}}))\n'
            'else:\n'
            '    assert sys.argv[3] == "9"\n'
            '    print(json.dumps({"link": "up", "ignored": "do-not-return"}))\n', encoding='utf-8')
        with patch.dict(os.environ, {'SHIFT_BRIDGE_DCO_PORT_SCRIPT': str(script),
                                     'HYBRID_API_AUTH_TOKEN': 'private-fixture-value'}):
            view = self.command('RACK-01 3번 스위치 포트 화면', dco.NAVIGATE,
                                rackId='RACK-01', switchId='3')
            self.assertEqual(view['type'], 'action_executed')
            self.assertEqual(view['action']['view'], 'tab-rack-ports')
            self.assertEqual(view['action']['switches'], [{'id': '3', 'ports': ['9', '10']}])
            result = self.command('3번 스위치 9번 포트 링크 상태', dco.CHECK_LINK,
                                  switchId='3', portId='9')
            self.assertEqual(result['action']['link'], 'up')
            self.assertEqual(result['auditLog']['targetId'], 'RACK-01/3/9')
            self.assertNotIn('do-not-return', json.dumps(result))
            all_ports = self.command('3번 스위치 링크 상태', dco.CHECK_LINK, switchId='3')
            self.assertEqual(all_ports['action']['ports'], [{'portId': '9', 'link': 'up'},
                                                            {'portId': '10', 'link': 'unknown'}])
            invalid = self.command('3번 스위치 11번 포트 링크', dco.CHECK_LINK,
                                   switchId='3', portId='11')
            self.assertEqual(invalid['type'], 'answer')
            with self.assertRaises(ai.ToolPermissionError):
                self.command('교체용 HDD 재고', dco.HDD_STOCK, member=self.member)

    def test_hdd_approval_is_atomic_and_cannot_oversubscribe_stock(self):
        message = 'RACK-01에 HDD-4TB 1개 반출 요청'
        request = {'sku': 'HDD-4TB', 'rackId': 'RACK-01', 'quantity': 1}
        first = self.command(message, dco.HDD_REQUEST, **request)
        second = self.command(message, dco.HDD_REQUEST, member=self.other_admin, **request)
        self.assertEqual(first['type'], 'pending_confirmation')
        self.assertEqual(first['changes']['quantity'], 1)
        self.assertEqual(self.command('HDD 재고', dco.HDD_STOCK)['action']['stock'],
                         [{'sku': 'HDD-4TB', 'available': 1}])
        self.assertIsNone(self.confirm(first, member=self.other_admin))
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(self.confirm, first)
            b = pool.submit(self.confirm, second, member=self.other_admin)
            responses = [a.result(), b.result()]
        self.assertCountEqual([item['status'] for item in responses], ['executed', 'cancelled'])
        self.assertEqual(self.confirm(first), responses[0])
        self.assertEqual(self.confirm(second, member=self.other_admin), responses[1])
        with db.get_connection() as conn:
            rows = conn.execute('SELECT item_id, quantity FROM dco_work_requests').fetchall()
        self.assertEqual([tuple(row) for row in rows], [('HDD-4TB', 1)])
        self.assertEqual(self.command('HDD-4TB 재고', dco.HDD_STOCK, sku='HDD-4TB')['action']['stock'],
                         [{'sku': 'HDD-4TB', 'available': 0}])

    def test_console_requires_approval_owner_current_role_and_unchanged_configuration(self):
        self.assertEqual(self.command('SRV-01 콘솔을 열어 줘', dco.OPEN_CONSOLE,
                                      serverId='fictitious')['type'], 'answer')
        pending = self.command('SRV-01 콘솔을 열어 줘', dco.OPEN_CONSOLE, serverId='SRV-01')
        identifier = pending['confirmationId']
        self.assertEqual(pending['target'], {'serverId': 'SRV-01', 'rackId': 'RACK-01'})
        self.assertIsNone(ai.console_redirect(identifier, self.admin))
        with self.assertRaises(ai.ToolPermissionError):
            self.confirm(pending, member={**self.admin, 'admin': False})
        approved = self.confirm(pending)
        self.assertEqual(approved['status'], 'executed')
        self.assertIn('/api/ai/console/' + identifier, approved['reply'])
        self.assertNotIn('fixture.invalid', json.dumps(approved))
        self.assertIsNone(ai.console_redirect(identifier, self.other_admin))
        self.assertEqual(ai.console_redirect(identifier, self.admin), 'https://fixture.invalid/console')
        self.inventory['servers']['SRV-01']['consoleUrl'] = 'https://changed.invalid/console'
        with patch.dict(os.environ, {'SHIFT_BRIDGE_DCO_INVENTORY_JSON': json.dumps(self.inventory)}):
            self.assertIsNone(ai.console_redirect(identifier, self.admin))

    def test_wipe_registration_persists_drafts_and_masks_request_credentials(self):
        secret = 'synthetic-private-value'
        message = f'SN-9921 와이핑 작업 등록 API 키: {secret}'
        pending = self.command(message, dco.WIPE_REQUEST, serialNumber='SN-9921')
        self.assertEqual(pending['target'], self.target)
        self.assertNotIn(secret, json.dumps(pending))
        with db.get_connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM dco_work_requests').fetchone()[0], 0)
        confirmed = self.confirm(pending)
        self.assertEqual(confirmed['status'], 'executed')
        self.assertIn('폐기 라벨 초안', confirmed['reply'])
        self.assertIn('와이핑 결과: 미확인', confirmed['reply'])
        self.assertEqual(self.confirm(pending), confirmed)
        duplicate = self.command('SN-9921 와이핑 등록', dco.WIPE_REQUEST, serialNumber='SN-9921')
        self.assertEqual(self.confirm(duplicate)['status'], 'cancelled')
        with db.get_connection() as conn:
            records = conn.execute('SELECT details FROM dco_work_requests').fetchall()
        self.assertEqual(len(records), 1)
        data = json.loads(records[0]['details'])
        self.assertIn('SN-9921', data['labelDraft'])
        self.assertIn('검증 증적: 미첨부', data['evidenceDraft'])
        events = [json.loads(row['detail']) for row in db.get_audit_trails()]
        self.assertTrue(any(event['requestMessage'].endswith('[가림]') for event in events))
        self.assertNotIn(secret, json.dumps(events))

    def test_expired_confirmation_cannot_change_state(self):
        pending = self.command('SN-9921 와이핑 등록', dco.WIPE_REQUEST, serialNumber='SN-9921')
        with db.get_connection() as conn:
            conn.execute('UPDATE ai_tool_confirmations SET expires_at = 0 WHERE id = ?',
                         (pending['confirmationId'],))
        result = self.confirm(pending)
        self.assertEqual((result['status'], result['auditLog']['result']), ('cancelled', 'expired'))
        self.assertEqual(self.confirm(pending), result)

    def test_old_ticket_confirmation_remains_usable_after_upgrade(self):
        log_id = db.add_work_log({'ticket_no': 'TT-42', 'device_id': 'SRV-01', 'status': '미완료'})
        confirmation = {'confirmationId': 'legacy-confirmation', 'approved': True}
        with db.get_connection() as conn:
            conn.execute("""INSERT INTO ai_confirmations
                (id, actor_id, log_id, ticket_no, device_id, expected_status, new_status)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (confirmation['confirmationId'], self.admin['id'], log_id, 'TT-42', 'SRV-01', '미완료', '완료'))
        confirmed = ai.confirm(confirmation, self.admin)
        self.assertEqual(confirmed['status'], 'executed')
        self.assertEqual(ai.confirm(confirmation, self.admin), confirmed)
        self.assertIn('다음 교대 인계', db.get_work_log_by_id(log_id)['follow_up'])
