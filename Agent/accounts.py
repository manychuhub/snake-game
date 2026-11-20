"""Web accounts, sessions, and usage. All account data stays in the main SQLite database."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import getpass
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time

import database as db

DAILY_LIMIT = 3
KST = timezone(timedelta(hours=9))
SESSION_SECONDS = 12 * 60 * 60


class QuotaExceeded(Exception):
    pass


def init():
    with db.get_connection(db.DB_PATH) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS web_users (
            id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
            admin INTEGER NOT NULL DEFAULT 0, whitelisted INTEGER NOT NULL DEFAULT 0
        );
        CREATE UNIQUE INDEX IF NOT EXISTS web_single_admin ON web_users(admin) WHERE admin = 1;
        CREATE TABLE IF NOT EXISTS web_sessions (
            token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS web_events (
            id INTEGER PRIMARY KEY, username TEXT NOT NULL, category TEXT NOT NULL,
            feature TEXT NOT NULL, result TEXT NOT NULL, day TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS web_events_category ON web_events(category, id);
        CREATE INDEX IF NOT EXISTS web_events_quota ON web_events(username, category, day, result);
        """)


def workspace_path(user_id):
    return db.DB_PATH.with_name(f'{db.DB_PATH.stem}-member-{user_id}.db')


def normalize(username):
    return username.strip().lower() if isinstance(username, str) else ''


def password_digest(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(errors='surrogatepass'), bytes.fromhex(salt), 600_000).hex()


def encode_password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError('비밀번호는 12~256자로 입력하세요.')
    salt = secrets.token_hex(16)
    return salt + ':' + password_digest(password, salt)


def create_user(username, password, *, admin=False):
    username = normalize(username)
    if not re.fullmatch(r'[a-z0-9_.-]{3,64}', username):
        raise ValueError('아이디는 영문, 숫자, 점, 밑줄, 하이픈을 사용해 3~64자로 입력하세요.')
    if not admin and username == normalize(os.getenv('SHIFT_BRIDGE_ADMIN_USER', 'admin')):
        raise ValueError('사용할 수 없는 아이디입니다.')
    encoded_password = encode_password(password)
    with db.get_connection(db.DB_PATH) as conn:
        try:
            cursor = conn.execute('INSERT INTO web_users(username,password,admin) VALUES(?,?,?)',
                         (username, encoded_password, int(admin)))
        except sqlite3.IntegrityError:
            raise ValueError('이미 사용 중인 아이디이거나 관리자 계정이 존재합니다.') from None
        if not admin:
            workspace = db.workspace_db.set(workspace_path(cursor.lastrowid))
            try:
                db.init_db(seed=False)
            finally:
                db.workspace_db.reset(workspace)


def bootstrap_admin(username, password, *, update_password=False):
    with db.get_connection(db.DB_PATH) as conn:
        conn.execute('BEGIN IMMEDIATE')
        admin = conn.execute('SELECT id,password FROM web_users WHERE admin=1').fetchone()
        if admin:
            if update_password:
                salt, expected = admin['password'].split(':')
                if not hmac.compare_digest(password_digest(password, salt), expected):
                    set_admin_password(conn, admin['id'], encode_password(password))
            return
    create_user(username, password, admin=True)


def set_admin_password(conn, user_id, encoded_password):
    conn.execute('UPDATE web_users SET password=? WHERE id=?', (encoded_password, user_id))
    conn.execute('DELETE FROM web_sessions WHERE user_id=?', (user_id,))


def reset_admin_password(username, password):
    encoded_password = encode_password(password)
    with db.get_connection(db.DB_PATH) as conn:
        conn.execute('BEGIN IMMEDIATE')
        user = conn.execute('SELECT id FROM web_users WHERE username=? AND admin=1',
                            (normalize(username),)).fetchone()
        if user is None:
            raise ValueError('관리자 계정을 찾을 수 없습니다.')
        set_admin_password(conn, user['id'], encoded_password)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def login(username, password):
    username = normalize(username)
    if not re.fullmatch(r'[a-z0-9_.-]{3,64}', username):
        username = ''
    with db.get_connection(db.DB_PATH) as conn:
        user = conn.execute('SELECT * FROM web_users WHERE username=?', (username,)).fetchone()
        valid_password = isinstance(password, str) and 0 < len(password) <= 256
        salt, expected = user['password'].split(':') if user else ('0' * 32, '0' * 64)
        matched = hmac.compare_digest(password_digest(password if valid_password else '', salt), expected)
        accepted = bool(user and valid_password and matched)
        if accepted:
            conn.execute('BEGIN IMMEDIATE')
            current = conn.execute('SELECT password FROM web_users WHERE id=?', (user['id'],)).fetchone()
            accepted = bool(current and hmac.compare_digest(current['password'], user['password']))
        add_event(conn, username, 'login', '로그인', 'success' if accepted else 'failed')
        if accepted:
            token = secrets.token_urlsafe(32)
            conn.execute('DELETE FROM web_sessions WHERE expires <= ?', (int(time.time()),))
            conn.execute('INSERT INTO web_sessions VALUES(?,?,?)',
                         (token_hash(token), user['id'], int(time.time()) + SESSION_SECONDS))
            return token
    return None


def session(token):
    if not token:
        return None
    with db.get_connection(db.DB_PATH) as conn:
        return conn.execute(
            'SELECT u.id,u.username,u.admin,u.whitelisted FROM web_sessions s JOIN web_users u '
            'ON u.id=s.user_id WHERE s.token=? AND s.expires>?',
            (token_hash(token), int(time.time()))).fetchone()


def logout(token):
    with db.get_connection(db.DB_PATH) as conn:
        conn.execute('DELETE FROM web_sessions WHERE token=?', (token_hash(token),))


def today():
    return datetime.now(KST).date().isoformat()


def add_event(conn, username, category, feature, result, day=None):
    return conn.execute('INSERT INTO web_events(username,category,feature,result,day) VALUES(?,?,?,?,?)',
                        (username, category, feature, result, day or today())).lastrowid


def feature_event(username, feature, status):
    with db.get_connection(db.DB_PATH) as conn:
        add_event(conn, username, 'feature', feature, str(status))


def ai_count(conn, username, day):
    return conn.execute(
        "SELECT count(*) FROM web_events WHERE username=? AND category='ai' AND day=? AND result!='limited'",
        (username, day)).fetchone()[0]


def remaining(user):
    if user['admin'] or user['whitelisted']:
        return None
    with db.get_connection(db.DB_PATH) as conn:
        return max(0, DAILY_LIMIT - ai_count(conn, user['username'], today()))


@contextmanager
def track_generation(user, feature):
    username = user['username']
    with db.get_connection(db.DB_PATH) as conn:
        conn.execute('BEGIN IMMEDIATE')
        current = conn.execute('SELECT admin,whitelisted FROM web_users WHERE id=?', (user['id'],)).fetchone()
        day = today()
        limited = not (current['admin'] or current['whitelisted']) and ai_count(conn, username, day) >= DAILY_LIMIT
        event_id = add_event(conn, username, 'ai', feature, 'limited' if limited else 'started', day)
    if limited:
        raise QuotaExceeded
    result = 'failed'
    try:
        yield
        result = 'success'
    finally:
        with db.get_connection(db.DB_PATH) as conn:
            conn.execute('UPDATE web_events SET result=? WHERE id=?', (result, event_id))


def dashboard(category, before, query=''):
    with db.get_connection(db.DB_PATH) as conn:
        events = conn.execute(
            'SELECT id,username,feature,result,created_at FROM web_events '
            'WHERE category=? AND id<? AND instr(username,?)>0 ORDER BY id DESC LIMIT 101',
            (category, before, query)).fetchall()
        return {
            'events': [dict(row) for row in events[:100]],
            'next': events[99]['id'] if len(events) > 100 else None,
        }


def members(query, before):
    with db.get_connection(db.DB_PATH) as conn:
        rows = conn.execute(
            'SELECT id,username,whitelisted FROM web_users WHERE admin=0 AND id<? '
            'AND instr(username,?)>0 ORDER BY id DESC LIMIT 101', (before, query)).fetchall()
        return {'users': [dict(row) for row in rows[:100]], 'next': rows[99]['id'] if len(rows) > 100 else None}


def whitelist(user_id, enabled, actor):
    with db.get_connection(db.DB_PATH) as conn:
        cursor = conn.execute('UPDATE web_users SET whitelisted=? WHERE id=? AND admin=0', (enabled, user_id))
        if cursor.rowcount:
            add_event(conn, actor, 'feature', '화이트리스트 ' + ('추가' if enabled else '해제'), f'계정 #{user_id}')
        return bool(cursor.rowcount)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SHIFT BRIDGE 관리자 계정 관리')
    parser.add_argument('username')
    parser.add_argument('--reset-password', action='store_true', help='기존 관리자 비밀번호를 재설정합니다.')
    args = parser.parse_args()
    password = getpass.getpass('관리자 비밀번호: ')
    if password != getpass.getpass('비밀번호 확인: '):
        parser.error('비밀번호가 일치하지 않습니다.')
    init()
    try:
        if args.reset_password:
            reset_admin_password(args.username, password)
        else:
            create_user(args.username, password, admin=True)
    except ValueError as error:
        parser.error(str(error))
    print('관리자 비밀번호를 재설정했습니다.' if args.reset_password else '관리자 계정을 생성했습니다.')
