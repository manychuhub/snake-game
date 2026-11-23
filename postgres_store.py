"""PostgreSQL services used by the web app and BridgeCLI."""
from contextlib import contextmanager

import psycopg
from psycopg.conninfo import conninfo_to_dict

WEB_DSN = 'SHIFT_BRIDGE_DATABASE_URL'
ENGINE_DSN = 'SHIFT_BRIDGE_ENGINE_DATABASE_URL'
RLS_TABLES = ('web_preferences', 'work_logs', 'handover_reports', 'technical_documents', 'missing_queries',
              'audit_trails', 'ai_confirmations', 'ai_notifications', 'ai_tool_confirmations', 'dco_work_requests')


class StorageError(RuntimeError):
    pass


class Row(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def row_factory(cursor):
    columns = [column.name for column in cursor.description or ()]
    return lambda values: Row((key, value) for key, value in zip(columns, values)
                              if key not in ('workspace_id', 'search_vector'))


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, statement, params=None):
        self.cursor.execute(statement.replace('?', '%s'), params)
        return self

    def executemany(self, statement, params):
        self.cursor.executemany(statement.replace('?', '%s'), params)

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def __iter__(self):
        return iter(self.cursor)


class Connection:
    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return Cursor(self.connection.cursor())

    def execute(self, statement, params=None):
        return self.cursor().execute(statement, params)

    def commit(self):
        self.connection.commit()


def connect(dsn, **kwargs):
    try:
        options = conninfo_to_dict(dsn)
        host = options.get('host', '')
        loopback = {'127.0.0.1', 'localhost', '::1'}
        local = host in loopback and options.get('hostaddr', host) in loopback
        if not local and options.get('sslmode') != 'verify-full':
            raise StorageError('Remote PostgreSQL requires sslmode=verify-full.')
        return psycopg.connect(dsn, connect_timeout=5, prepare_threshold=None, **kwargs)
    except psycopg.Error:
        raise StorageError('Could not connect to PostgreSQL.') from None


@contextmanager
def database(dsn, *, engine=False, workspace=None, account=None):
    schema = 'shiftbridge_engine' if engine else 'shiftbridge_web'
    try:
        with connect(dsn, row_factory=row_factory) as conn:
            conn.execute(f'SET LOCAL search_path TO pg_catalog, {schema}')
            conn.execute("""SELECT set_config('statement_timeout', '15000', true),
                set_config('shift_bridge.workspace_id', %s, true), set_config('shift_bridge.account_id', %s, true)""",
                         (str(workspace) if workspace is not None else '', str(account) if account is not None else ''))
            yield Connection(conn)
    except psycopg.Error:
        raise StorageError('A PostgreSQL operation failed.') from None


def verify(dsn, *, engine=False):
    role = 'shift_bridge_engine' if engine else 'shift_bridge_web'
    with database(dsn, engine=engine) as conn:
        if conn.execute('SELECT current_user').fetchone()[0] != role:
            raise StorageError(f'PostgreSQL must use the {role} runtime role.')
        if conn.execute('SELECT 1 FROM shiftbridge_web.sqlite_import WHERE id=1').fetchone() is None:
            raise StorageError('The verified SQLite import marker is missing.')
        if engine:
            conn.execute('SELECT 1 FROM records LIMIT 0')
            return
        for table in RLS_TABLES:
            if not conn.execute('SELECT row_security_active(?::regclass)', (table,)).fetchone()[0]:
                raise StorageError('PostgreSQL account or workspace RLS is inactive.')
