"""Web accounts, sessions, and usage."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import getpass
import hashlib
import hmac
import os
import re
import secrets
import time

import database as db

DAILY_LIMIT = 3
KST = timezone(timedelta(hours=9))
SESSION_SECONDS = 12 * 60 * 60
PREFERENCE_LIMITS = {'default_location': 120, 'place_type': 80}


class QuotaExceeded(Exception):
    pass


class SessionExpired(Exception):
    pass


class LastAdministrator(Exception):
    pass


def init():
    if db.postgres_enabled():
        import postgres_store
        postgres_store.verify(os.environ['SHIFT_BRIDGE_DATABASE_URL'])
        return
    with db.get_connection(db.DB_PATH) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS web_users (
            id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
            admin INTEGER NOT NULL DEFAULT 0, whitelisted INTEGER NOT NULL DEFAULT 0,
            retired INTEGER NOT NULL DEFAULT 0, bootstrap_password TEXT
        );
        CREATE TABLE IF NOT EXISTS web_sessions (
            token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS web_preferences (
            user_id INTEGER PRIMARY KEY REFERENCES web_users(id),
            default_location TEXT NOT NULL DEFAULT '', place_type TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS web_events (
            id INTEGER PRIMARY KEY, username TEXT NOT NULL, category TEXT NOT NULL,
            feature TEXT NOT NULL, result TEXT NOT NULL, day TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS web_events_category ON web_events(category, id);
        CREATE INDEX IF NOT EXISTS web_events_quota ON web_events(username, category, day, result);
        """)
        db.lock_accounts(conn)
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(web_users)')}
        if 'retired' not in columns:
            conn.execute('ALTER TABLE web_users ADD COLUMN retired INTEGER NOT NULL DEFAULT 0')
        if 'bootstrap_password' not in columns:
            conn.execute('ALTER TABLE web_users ADD COLUMN bootstrap_password TEXT')
        conn.execute('DROP INDEX IF EXISTS web_single_admin')


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


def password_matches(password, encoded):
    valid = isinstance(password, str) and 0 < len(password) <= 256
    salt, expected = encoded.split(':') if encoded else ('0' * 32, '0' * 64)
    matched = hmac.compare_digest(password_digest(password if valid else '', salt), expected)
    return bool(encoded and valid and matched)


def validated_username(username):
    username = normalize(username)
    if not re.fullmatch(r'[a-z0-9_.-]{3,64}', username):
        raise ValueError('아이디는 영문, 숫자, 점, 밑줄, 하이픈을 사용해 3~64자로 입력하세요.')
    return username


def create_user(username, password, *, admin=False):
    username = validated_username(username)
    if not admin and username == normalize(os.getenv('SHIFT_BRIDGE_ADMIN_USER', 'admin')):
        raise ValueError('사용할 수 없는 아이디입니다.')
    encoded_password = encode_password(password)
    with db.get_connection(db.DB_PATH) as conn:
        values = (username, encoded_password, int(admin))
        if db.postgres_enabled():
            row = conn.execute('INSERT INTO web_users(username,password,admin,personal_workspace) VALUES(?,?,?,?) '
                               'ON CONFLICT(username) DO NOTHING RETURNING id', (*values, int(not admin))).fetchone()
        else:
            row = conn.execute('INSERT INTO web_users(username,password,admin) VALUES(?,?,?) '
                               'ON CONFLICT(username) DO NOTHING RETURNING id', values).fetchone()
        if row is None:
            raise ValueError('사용할 수 없는 아이디입니다.')
        if not admin and not db.postgres_enabled():
            workspace = db.workspace_db.set(workspace_path(row[0]))
            try:
                db.init_db(seed=False)
            finally:
                db.workspace_db.reset(workspace)


def bootstrap_admin(username, password, *, update_password=False):
    username = validated_username(username)
    with db.get_connection(db.DB_PATH) as conn:
        db.lock_accounts(conn)
        user = conn.execute('SELECT * FROM web_users WHERE username=?', (username,)).fetchone()
        if user is None:
            encoded = encode_password(password)
            conn.execute('INSERT INTO web_users(username,password,admin,bootstrap_password) VALUES(?,?,1,?)',
                         (username, encoded, encoded if update_password else None))
            return
        if user['retired'] or not user['admin'] or not update_password:
            return
        # Ordinary redeploys must preserve passwords changed by the user. A new environment value rotates it.
        previous = user['bootstrap_password']
        if previous and password_matches(password, previous):
            return
        encoded = user['password']
        if not password_matches(password, encoded):
            encoded = encode_password(password)
            set_password(conn, user['id'], encoded)
        conn.execute('UPDATE web_users SET bootstrap_password=? WHERE id=?', (encoded, user['id']))


def revoke_sessions(conn, user_id):
    conn.execute('DELETE FROM web_sessions WHERE user_id=?', (user_id,))


def set_password(conn, user_id, encoded_password):
    conn.execute('UPDATE web_users SET password=? WHERE id=?', (encoded_password, user_id))
    revoke_sessions(conn, user_id)


def reset_admin_password(username, password):
    encoded_password = encode_password(password)
    with db.get_connection(db.DB_PATH) as conn:
        db.lock_accounts(conn)
        user = conn.execute('SELECT id FROM web_users WHERE username=? AND admin=1 AND retired=0',
                            (normalize(username),)).fetchone()
        if user is None:
            raise ValueError('관리자 계정을 찾을 수 없습니다.')
        set_password(conn, user['id'], encoded_password)


def grant_admin(username, password):
    with db.get_connection(db.DB_PATH) as conn:
        db.lock_accounts(conn)
        user = conn.execute('SELECT id,password,admin FROM web_users WHERE username=? AND retired=0',
                            (normalize(username),)).fetchone()
        if user is None or not password_matches(password, user['password']):
            raise ValueError('활성 계정과 현재 비밀번호를 확인하세요.')
        if not user['admin']:
            conn.execute('UPDATE web_users SET admin=1 WHERE id=?', (user['id'],))
            revoke_sessions(conn, user['id'])


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def login(username, password):
    username = normalize(username)
    if not re.fullmatch(r'[a-z0-9_.-]{3,64}', username):
        username = ''
    with db.get_connection(db.DB_PATH) as conn:
        user = conn.execute('SELECT id,password FROM web_users WHERE username=? AND retired=0', (username,)).fetchone()
        accepted = password_matches(password, user['password'] if user else None)
        if accepted:
            db.lock_accounts(conn)
            current = conn.execute('SELECT password FROM web_users WHERE id=? AND retired=0', (user['id'],)).fetchone()
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
        return session_user(conn, token)


def session_user(conn, token, *, credentials=False):
    columns = 'u.id,u.username,u.admin,u.whitelisted' + (',u.password' if credentials else '')
    if db.postgres_enabled():
        columns += ',u.personal_workspace'
    return conn.execute(
        f'SELECT {columns} FROM web_sessions s JOIN web_users u ON u.id=s.user_id '
        'WHERE s.token=? AND s.expires>? AND u.retired=0',
        (token_hash(token), int(time.time()))).fetchone()


def logout(token):
    with db.get_connection(db.DB_PATH) as conn:
        db.lock_accounts(conn)
        conn.execute('DELETE FROM web_sessions WHERE token=?', (token_hash(token),))


def change_account(user_id, token, current_password, *, new_password=None, delete=False):
    with db.get_connection(db.DB_PATH, account_id=user_id) as conn:
        user = session_user(conn, token, credentials=True)
        if user is None or user['id'] != user_id:
            raise SessionExpired
        if not password_matches(current_password, user['password']):
            raise ValueError('현재 비밀번호를 확인하세요.')
        if not delete:
            if current_password == new_password:
                raise ValueError('현재 비밀번호와 다른 새 비밀번호를 입력하세요.')
            encoded = encode_password(new_password)

        db.lock_accounts(conn)
        current = session_user(conn, token, credentials=True)
        if (current is None or current['id'] != user_id
                or not hmac.compare_digest(current['password'], user['password'])):
            raise SessionExpired
        if not delete:
            set_password(conn, user_id, encoded)
            return
        if current['admin'] and not conn.execute(
                'SELECT 1 FROM web_users WHERE admin=1 AND retired=0 AND id<>?', (user_id,)).fetchone():
            raise LastAdministrator
        revoke_sessions(conn, user_id)
        conn.execute('DELETE FROM web_preferences WHERE user_id=?', (user_id,))
        # Keep the ID and username reserved while retaining work records and audit history.
        conn.execute('''UPDATE web_users SET retired=1, password='', bootstrap_password=NULL,
                        admin=0, whitelisted=0 WHERE id=?''', (user_id,))


def get_preferences(user_id):
    with db.get_connection(db.DB_PATH, account_id=user_id) as conn:
        row = conn.execute(
            'SELECT default_location,place_type FROM web_preferences WHERE user_id=?',
            (user_id,)).fetchone()
    return dict(row) if row else dict.fromkeys(PREFERENCE_LIMITS, '')


def save_preferences(user_id, token, body):
    preferences = {}
    for field, limit in PREFERENCE_LIMITS.items():
        value = body.get(field)
        if not isinstance(value, str):
            raise ValueError('기본 위치와 장소 종류를 문자열로 입력하세요.')
        if value and not value.isprintable():
            raise ValueError('기본 위치와 장소 종류는 한 줄로 입력하세요.')
        value = value.strip()
        if len(value) > limit:
            raise ValueError('기본 위치는 120자, 장소 종류는 80자까지 입력할 수 있습니다.')
        preferences[field] = value

    with db.get_connection(db.DB_PATH, account_id=user_id) as conn:
        db.lock_accounts(conn)
        # Check revocation in the write itself so logout and save are ordered by SQLite.
        cursor = conn.execute('''
            INSERT INTO web_preferences(user_id,default_location,place_type)
            SELECT user_id,?,? FROM web_sessions WHERE token=? AND user_id=? AND expires>?
            ON CONFLICT(user_id) DO UPDATE SET
                default_location=excluded.default_location, place_type=excluded.place_type
        ''', (preferences['default_location'], preferences['place_type'], token_hash(token), user_id,
              int(time.time())))
        return preferences if cursor.rowcount else None


def today():
    return datetime.now(KST).date().isoformat()


def add_event(conn, username, category, feature, result, day=None):
    return conn.execute('INSERT INTO web_events(username,category,feature,result,day) VALUES(?,?,?,?,?) RETURNING id',
                        (username, category, feature, result, day or today())).fetchone()[0]


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
        db.lock_accounts(conn)
        current = conn.execute('SELECT admin,whitelisted FROM web_users WHERE id=? AND retired=0', (user['id'],)).fetchone()
        if current is None:
            raise SessionExpired
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
    substring = 'strpos' if db.postgres_enabled() else 'instr'
    with db.get_connection(db.DB_PATH) as conn:
        events = conn.execute(
            'SELECT id,username,feature,result,created_at FROM web_events '
            f'WHERE category=? AND id<? AND {substring}(username,?)>0 ORDER BY id DESC LIMIT 101',
            (category, before, query)).fetchall()
        return {
            'events': [dict(row) for row in events[:100]],
            'next': events[99]['id'] if len(events) > 100 else None,
        }


def members(query, before):
    substring = 'strpos' if db.postgres_enabled() else 'instr'
    with db.get_connection(db.DB_PATH) as conn:
        rows = conn.execute(
            'SELECT id,username,whitelisted FROM web_users WHERE admin=0 AND retired=0 AND id<? '
            f'AND {substring}(username,?)>0 ORDER BY id DESC LIMIT 101', (before, query)).fetchall()
        return {'users': [dict(row) for row in rows[:100]], 'next': rows[99]['id'] if len(rows) > 100 else None}


def whitelist(user_id, enabled, actor):
    with db.get_connection(db.DB_PATH) as conn:
        cursor = conn.execute('UPDATE web_users SET whitelisted=? WHERE id=? AND admin=0 AND retired=0', (enabled, user_id))
        if cursor.rowcount:
            add_event(conn, actor, 'feature', '화이트리스트 ' + ('추가' if enabled else '해제'), f'계정 #{user_id}')
        return bool(cursor.rowcount)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SHIFT BRIDGE 관리자 계정 관리')
    parser.add_argument('username')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--reset-password', action='store_true', help='기존 관리자 비밀번호를 재설정합니다.')
    mode.add_argument('--grant-admin', action='store_true', help='기존 계정에 관리자 권한을 부여합니다.')
    args = parser.parse_args()
    password = getpass.getpass('현재 비밀번호: ' if args.grant_admin else '관리자 비밀번호: ')
    if not args.grant_admin and password != getpass.getpass('비밀번호 확인: '):
        parser.error('비밀번호가 일치하지 않습니다.')
    init()
    try:
        if args.reset_password:
            reset_admin_password(args.username, password)
            result = '관리자 비밀번호를 재설정했습니다.'
        elif args.grant_admin:
            grant_admin(args.username, password)
            result = '관리자 권한을 부여했습니다.'
        else:
            create_user(args.username, password, admin=True)
            result = '관리자 계정을 생성했습니다.'
    except ValueError as error:
        parser.error(str(error))
    print(result)
