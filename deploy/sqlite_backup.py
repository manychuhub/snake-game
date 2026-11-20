"""Copy accessible SHIFT BRIDGE SQLite files using SQLite's online backup API."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

WORK_TABLES = ('work_logs', 'handover_reports', 'technical_documents', 'missing_queries', 'audit_trails')
ACCOUNT_TABLES = ('web_users', 'web_sessions', 'web_preferences', 'web_events')
ENGINE_TABLES = ('records', 'reports', 'documents', 'usage')


def read_only(path):
    conn = sqlite3.connect(path.resolve(strict=True).as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return closing(conn)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def table_counts(conn, known_tables):
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    return {name: conn.execute(f'SELECT count(*) FROM {name}').fetchone()[0]
            for name in known_tables if name in tables}


def copy_database(source, target, tables):
    with read_only(source) as incoming:
        target.touch(mode=0o600, exist_ok=False)
        with closing(sqlite3.connect(target)) as outgoing:
            incoming.backup(outgoing)
            if [row[0] for row in outgoing.execute('PRAGMA integrity_check')] != ['ok']:
                raise ValueError(f'Integrity check failed for {target.name}.')
            counts = table_counts(outgoing, tables)
    return {'file': target.name, 'sha256': digest(target), 'tables': counts}


def backup(web_db, directory, engine_db=None):
    web_db = web_db.resolve(strict=True)
    if engine_db is not None:
        engine_db = engine_db.resolve(strict=True)
    directory.mkdir(mode=0o700)
    files = [dict(copy_database(web_db, directory / 'web.db', ACCOUNT_TABLES + WORK_TABLES),
                  kind='web', workspace_id=0)]
    if 'web_users' not in files[0]['tables']:
        raise ValueError('The main database does not contain the web account table.')
    workspace_pattern = re.compile(re.escape(web_db.stem) + r'-member-([1-9][0-9]*)\.db')
    for path in sorted(web_db.parent.glob(f'{web_db.stem}-member-*.db')):
        match = workspace_pattern.fullmatch(path.name)
        if not match:
            raise ValueError('Unexpected member database filename.')
        workspace_id = int(match[1])
        entry = copy_database(path, directory / f'member-{workspace_id}.db', WORK_TABLES)
        files.append(dict(entry, kind='member', workspace_id=workspace_id))
    if engine_db is not None:
        files.append(dict(copy_database(engine_db, directory / 'engine.db', ENGINE_TABLES), kind='engine'))
    manifest = directory / 'manifest.json'
    manifest.touch(mode=0o600, exist_ok=False)
    manifest.write_text(json.dumps({'format': 1, 'databases': files}, indent=2) + '\n', encoding='utf-8')
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web-db', type=Path, required=True)
    parser.add_argument('--engine-db', type=Path)
    parser.add_argument('--output', type=Path, required=True, help='A new directory on private storage')
    args = parser.parse_args()
    try:
        files = backup(args.web_db, args.output, args.engine_db)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, f'SQLite backup failed: {error}\n')
    print(f'Verified SQLite backup completed for {len(files)} database files.')


if __name__ == '__main__':
    main()
