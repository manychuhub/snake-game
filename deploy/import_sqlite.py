"""Verify a SQLite backup and optionally restore it into empty SHIFT BRIDGE PostgreSQL tables."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from psycopg import Error, sql

from postgres_store import StorageError, connect
from sqlite_backup import ACCOUNT_TABLES, DCO_TABLES, ENGINE_TABLES, WORK_TABLES, digest, read_only, table_counts

WEB = 'shiftbridge_web'
ENGINE = 'shiftbridge_engine'
TARGETS = [(WEB, table) for table in (*ACCOUNT_TABLES, *WORK_TABLES, 'sqlite_import')]
TARGETS += [(ENGINE, table) for table in ENGINE_TABLES]


def validate_backup(directory):
    manifest_path = directory / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest['format'] != 1:
        raise ValueError('The backup manifest format is unsupported.')
    entries = manifest['databases']
    workspaces = set()
    seen = set()
    for entry in entries:
        kind = entry['kind']
        if kind == 'member':
            workspace = entry['workspace_id']
            if type(workspace) is not int or not 0 < workspace < 2**63:
                raise ValueError('The member workspace ID is invalid.')
            filename, tables = f'member-{workspace}.db', WORK_TABLES
            workspaces.add(workspace)
        elif kind == 'web' and entry['workspace_id'] == 0:
            filename, tables = 'web.db', ACCOUNT_TABLES + WORK_TABLES
        elif kind == 'engine':
            filename, tables = 'engine.db', ENGINE_TABLES
        else:
            raise ValueError('The backup contains an invalid database entry.')
        path = directory / filename
        if entry['file'] != filename or filename in seen or path.is_symlink() or digest(path) != entry['sha256']:
            raise ValueError(f'Backup file verification failed for {filename}.')
        seen.add(filename)
        with read_only(path) as conn:
            counts = table_counts(conn, tables)
            missing = set(tables) - counts.keys()
            optional_tables = {'web_sessions', 'web_preferences', 'web_events', 'ai_notifications', *DCO_TABLES}
            if counts != entry['tables'] or missing - optional_tables:
                raise ValueError(f'Backup schema or row count verification failed for {filename}.')
            if [row[0] for row in conn.execute('PRAGMA integrity_check')] != ['ok']:
                raise ValueError(f'SQLite integrity check failed for {filename}.')
    if not {'web.db', 'engine.db'} <= seen:
        raise ValueError('A complete restore needs both the web and BridgeCLI backups.')
    with read_only(directory / 'web.db') as conn:
        users = [dict(row) for row in conn.execute('SELECT id,admin' + (
            ',retired' if any(row['name'] == 'retired' for row in conn.execute('PRAGMA table_info(web_users)')) else ''
        ) + ' FROM web_users')]
    if not any(user['admin'] and not user.get('retired') for user in users):
        raise ValueError('The backup must include an active administrator.')
    if any(not user['admin'] and not user.get('retired') and user['id'] not in workspaces for user in users):
        raise ValueError('A member workspace file is missing from the backup.')
    if workspaces - {user['id'] for user in users}:
        raise ValueError('A member workspace has no matching account in the backup.')
    return entries, workspaces, digest(manifest_path)


def row_digest(rows):
    result = hashlib.sha256()
    count = 0
    for values in rows:
        result.update((json.dumps(list(values), ensure_ascii=False) + '\n').encode())
        count += 1
    return count, result.digest()


def copy_table(source, conn, schema, name, *, workspace=None, workspaces=()):
    key = 'user_id' if name == 'web_preferences' else 'id'
    # Only fixed table names reach this function. All destination identifiers are escaped.
    incoming = source.execute(f'SELECT * FROM {name} ORDER BY {key}')
    incoming_columns = [column[0] for column in incoming.description]
    columns = (['workspace_id'] if workspace is not None else []) + incoming_columns
    add_workspace_flag = name == 'web_users' and 'personal_workspace' not in columns
    if add_workspace_flag:
        columns.append('personal_workspace')
    table = sql.Identifier(schema, name)
    fields = sql.SQL(',').join(map(sql.Identifier, columns))
    insert = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
        table, fields, sql.SQL(',').join(sql.Placeholder() for _ in columns))
    checksum = hashlib.sha256()
    count = 0
    with conn.cursor() as cursor:
        while batch := incoming.fetchmany(500):
            values = [((workspace,) if workspace is not None else ()) + tuple(row)
                      + ((int(row['id'] in workspaces),) if add_workspace_flag else ()) for row in batch]
            cursor.executemany(insert, values)
            for row in values:
                checksum.update((json.dumps(list(row), ensure_ascii=False) + '\n').encode())
            count += len(values)

    select = sql.SQL('SELECT {} FROM {}').format(fields, table)
    if workspace is not None:
        select += sql.SQL(' WHERE workspace_id = %s')
    select += sql.SQL(' ORDER BY {}').format(sql.Identifier(key))
    with conn.cursor(name='verify_import_rows') as cursor:
        cursor.execute(select, (workspace,) if workspace is not None else None)
        if row_digest(cursor) != (count, checksum.digest()):
            raise ValueError(f'Row verification failed for {schema}.{name}.')
    return count


def restore(directory, dsn):
    entries, workspaces, manifest_hash = validate_backup(directory)
    with connect(dsn) as conn:
        conn.execute("SET LOCAL lock_timeout = '5s'")
        conn.execute(sql.SQL('LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE').format(
            sql.SQL(',').join(sql.Identifier(*target) for target in TARGETS)))
        for target in TARGETS:
            if conn.execute(sql.SQL('SELECT 1 FROM {} LIMIT 1').format(sql.Identifier(*target))).fetchone():
                raise ValueError('The target already contains SHIFT BRIDGE data. Restore stopped before writing.')

        count = 0
        for entry in sorted(entries, key=lambda item: item['kind'] != 'web'):
            schema = ENGINE if entry['kind'] == 'engine' else WEB
            with read_only(directory / entry['file']) as source:
                for name in (*ACCOUNT_TABLES, *WORK_TABLES, *ENGINE_TABLES):
                    if name not in entry['tables'] or name == 'web_sessions':
                        continue
                    workspace = entry['workspace_id'] if name in WORK_TABLES else None
                    count += copy_table(source, conn, schema, name, workspace=workspace, workspaces=workspaces)
            if digest(directory / entry['file']) != entry['sha256']:
                raise ValueError('A SQLite backup file changed during the restore.')
        for schema, name in TARGETS:
            if name in {'web_sessions', 'web_preferences', 'sqlite_import', 'ai_notifications', *DCO_TABLES}:
                continue
            table = sql.Identifier(schema, name)
            maximum = conn.execute(sql.SQL('SELECT coalesce(max(id), 0) FROM {}').format(table)).fetchone()[0]
            conn.execute(sql.SQL('ALTER TABLE {} ALTER COLUMN id RESTART WITH {}').format(table, sql.Literal(maximum + 1)))
        conn.execute('INSERT INTO shiftbridge_web.sqlite_import (id, manifest_sha256) VALUES (1, %s)', (manifest_hash,))
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup', type=Path)
    parser.add_argument('--apply', action='store_true', help='Write to empty PostgreSQL target tables')
    args = parser.parse_args()
    try:
        if args.apply:
            dsn = os.environ.get('SHIFT_BRIDGE_MIGRATION_DATABASE_URL')
            if not dsn:
                raise ValueError('Set SHIFT_BRIDGE_MIGRATION_DATABASE_URL securely before restoring.')
            count = restore(args.backup, dsn)
            print(f'Restored and verified {count} rows. Existing login sessions were excluded.')
        else:
            entries, _, _ = validate_backup(args.backup)
            print(f'Validated {len(entries)} SQLite backup files without connecting to PostgreSQL.')
    except (OSError, ValueError, KeyError, TypeError, StorageError) as error:
        parser.exit(1, f'Validation or import stopped: {error}\n')
    except (Error, sqlite3.Error):
        parser.exit(1, 'A database statement failed. The PostgreSQL restore was rolled back.\n')


if __name__ == '__main__':
    main()
