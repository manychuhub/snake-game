"""Integration test for an empty, disposable loopback PostgreSQL database."""
from contextlib import contextmanager, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

import accounts
import database
from import_sqlite import restore, validate_backup
from memory import Memory
import postgres_store
from sqlite_backup import backup

ROOT = Path(__file__).resolve().parents[1]
OWNER = os.environ.get('SHIFT_BRIDGE_TEST_DATABASE_URL')


@contextmanager
def web_server(dsn, sqlite_path):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    environment = {**os.environ, 'PORT': str(port), 'SHIFT_BRIDGE_WEB_HOST': '127.0.0.1',
                   'SHIFT_BRIDGE_DATABASE_URL': dsn, 'SHIFT_BRIDGE_DB_PATH': str(sqlite_path)}
    process = subprocess.Popen([sys.executable, 'app.py'], cwd=ROOT / 'Agent', env=environment)
    try:
        for _ in range(50):
            if process.poll() is not None:
                raise RuntimeError('Test web server stopped.')
            try:
                with urlopen(origin + '/healthz', timeout=0.5):
                    break
            except URLError:
                time.sleep(0.1)
        else:
            raise RuntimeError('Test web server did not start.')
        yield origin
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def request(origin, path, *, token=None, data=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Cookie'] = 'shift_session=' + token
    req = Request(origin + path, headers=headers, data=json.dumps(data).encode() if data is not None else None)
    try:
        with urlopen(req, timeout=4) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        with error:
            return error.code, json.load(error)


@unittest.skipUnless(OWNER, 'Set SHIFT_BRIDGE_TEST_DATABASE_URL for the disposable PostgreSQL test.')
class PostgresMigrationTest(unittest.TestCase):
    def test_verified_restore_and_web_restart_with_rls(self):
        options = conninfo_to_dict(OWNER)
        loopback = {'localhost', '127.0.0.1', '::1'}
        self.assertIn(options.get('host'), loopback)
        self.assertIn(options.get('hostaddr', options.get('host')), loopback)
        self.assertTrue(options.get('dbname', '').startswith('shift_bridge_test_'))
        with psycopg.connect(OWNER) as conn:
            migration = ROOT / 'supabase/migrations/20261120000100_shift_bridge_storage.sql'
            conn.execute(migration.read_text(encoding='utf-8'))
            conn.execute('ALTER ROLE shift_bridge_web LOGIN')
            conn.execute('ALTER ROLE shift_bridge_engine LOGIN')
        web = make_conninfo(OWNER, user='shift_bridge_web')
        engine = make_conninfo(OWNER, user='shift_bridge_engine')

        with TemporaryDirectory() as temp:
            root = Path(temp)
            sqlite_path = root / 'shift_bridge.db'
            engine_path = root / 'bridge.db'
            snapshot = root / 'backup'
            with patch.object(database, 'DB_PATH', sqlite_path), redirect_stdout(StringIO()):
                database.init_db(seed=False)
                accounts.init()
                accounts.create_user('fixture-admin', 'fictional-admin-password', admin=True)
                accounts.create_user('fixture-member', 'fictional-member-password')
                old_token = accounts.login('fixture-member', 'fictional-member-password')
                member_id = accounts.session(old_token)['id']
                accounts.save_preferences(member_id, old_token, {'default_location': '회원 위치', 'place_type': '시험실'})
                first_id = database.add_work_log({'raw_text': '관리자 기록', 'status': '완료'})
                selection = database.workspace_db.set(accounts.workspace_path(member_id))
                try:
                    self.assertEqual(database.add_work_log({'raw_text': '회원 기록', 'status': '완료'}), first_id)
                    database.save_handover_report({'raw_markdown': '이전 보고서'})
                    database.add_technical_doc('test.md', 'SOP', '테스트', '요약', '본문')
                finally:
                    database.workspace_db.reset(selection)
                legacy_engine = Memory(engine_path)
                legacy_engine.add({'summary': '엔진 기록'}, approved=True)
                legacy_engine.report({'content': '엔진 보고서'})
                backup(sqlite_path, snapshot, engine_path)

            self.assertEqual(len(validate_backup(snapshot)[0]), 3)
            self.assertGreater(restore(snapshot, OWNER), 0)
            with self.assertRaisesRegex(ValueError, 'already contains'):
                restore(snapshot, OWNER)
            with self.assertRaises(postgres_store.StorageError):
                postgres_store.verify(OWNER)
            with psycopg.connect(web) as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM shiftbridge_web.work_logs').fetchone()[0], 0)
                self.assertEqual(conn.execute('SELECT count(*) FROM shiftbridge_web.web_preferences').fetchone()[0], 0)
                conn.execute("SELECT set_config('shift_bridge.workspace_id', %s, true)", (str(member_id),))
                self.assertEqual(conn.execute('SELECT count(*) FROM shiftbridge_web.work_logs').fetchone()[0], 1)
                self.assertEqual(conn.execute('UPDATE shiftbridge_web.work_logs SET raw_text=%s WHERE workspace_id=0',
                                              ('out-of-scope fixture',)).rowcount, 0)
                with self.assertRaises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                    conn.execute('INSERT INTO shiftbridge_web.work_logs(workspace_id, raw_text) VALUES(0, %s)', ('fixture',))
                conn.execute("SELECT set_config('shift_bridge.account_id', %s, true)", (str(member_id),))
                self.assertEqual(conn.execute('SELECT count(*) FROM shiftbridge_web.web_preferences').fetchone()[0], 1)
                with self.assertRaises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                    conn.execute('INSERT INTO shiftbridge_web.web_preferences(user_id) VALUES(1)')
            with psycopg.connect(engine) as conn:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                    conn.execute('SELECT password FROM shiftbridge_web.web_users')
            with psycopg.connect(web) as conn:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                    conn.execute('SELECT body FROM shiftbridge_engine.records')

            with patch.dict(os.environ, {'SHIFT_BRIDGE_DATABASE_URL': web, 'SHIFT_BRIDGE_ENGINE_DATABASE_URL': engine}):
                self.assertIsNone(accounts.session(old_token))
                member = accounts.login('fixture-member', 'fictional-member-password')
                admin = accounts.login('fixture-admin', 'fictional-admin-password')
                self.assertTrue(member and admin)
                self.assertEqual(Memory().rows()[0]['summary'], '엔진 기록')
                self.assertEqual(Memory().reports()[0]['content'], '엔진 보고서')
                Memory().add_doc('fixture', 1, '저장')
                self.assertEqual(Memory().docs()[0]['text'], '저장')
                with web_server(web, root / 'unavailable.db') as origin:
                    self.assertEqual(request(origin, '/api/logs')[0], 401)
                    self.assertEqual(request(origin, '/api/logs', token=admin)[1]['logs'][0]['raw_text'], '관리자 기록')
                    self.assertEqual(request(origin, '/api/logs', token=member)[1]['logs'][0]['raw_text'], '회원 기록')
                    values = request(origin, '/api/account/preferences', token=member)[1]
                    self.assertEqual(values['default_location'], '회원 위치')
                    self.assertEqual(request(origin, '/api/account/preferences', token=admin,
                                             data=values)[0], 409)
                    self.assertEqual(request(origin, '/api/account/preferences', token=member,
                                             data={**values, 'default_location': '변경 위치'})[0], 200)
                    status, saved = request(origin, '/api/logs/create', token=member,
                                            data={'raw_text': '새 업무 기록', 'status': '완료'})
                    self.assertEqual(status, 200)
                    self.assertGreater(saved['log']['id'], first_id)
                    self.assertEqual(request(origin, '/api/logs/update', token=member,
                                             data={'id': first_id, 'raw_text': '회원의 수정', 'workspace_id': 0})[0], 200)
                    self.assertEqual(request(origin, '/api/logs', token=admin)[1]['logs'][0]['raw_text'], '관리자 기록')
                workspace = database.workspace_id.set(member_id)
                try:
                    self.assertIn('새 업무 기록', json.dumps(database.search_rag_knowledge('업무 기록'), ensure_ascii=False))
                finally:
                    database.workspace_id.reset(workspace)
                with web_server(web, root / 'unavailable.db') as origin:
                    self.assertEqual(request(origin, '/api/logs', token=member)[1]['logs'][0]['raw_text'], '새 업무 기록')
                    values = request(origin, '/api/account/preferences', token=member)[1]
                    self.assertEqual(values['default_location'], '변경 위치')
                    status, _ = request(origin, '/api/account/password', token=member, data={
                        'account_id': values['account_id'], 'current_password': 'fictional-member-password',
                        'new_password': 'fictional-password-changed',
                    })
                    self.assertEqual(status, 200)
                    self.assertEqual(request(origin, '/api/account/me', token=member)[0], 401)
                    self.assertIsNone(accounts.login('fixture-member', 'fictional-member-password'))
                    member = accounts.login('fixture-member', 'fictional-password-changed')
                    self.assertTrue(member)
                    self.assertEqual(request(origin, '/api/account/delete', token=member, data={
                        'account_id': values['account_id'], 'current_password': 'fictional-password-changed',
                        'confirmed': True,
                    })[0], 200)
                    self.assertIsNone(accounts.session(member))
                    self.assertEqual(accounts.get_preferences(member_id)['default_location'], '')
                self.assertFalse((root / 'unavailable.db').exists())


if __name__ == '__main__':
    unittest.main()
