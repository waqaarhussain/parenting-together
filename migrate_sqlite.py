"""Copy a stopped application's SQLite database into an empty PostgreSQL database.

The source is read-only. All inserts, verification and the migration marker share
one transaction. A failed copy leaves no partially imported application rows.
"""
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from psycopg import sql
from psycopg.rows import tuple_row
from database import connect, initialize_postgres

TABLES = ('users', 'user_vaults', 'families', 'family_members', 'family_invites',
          'children', 'messages', 'message_reads', 'typing_status', 'events',
          'handovers', 'decisions', 'expenses', 'rules', 'audit', 'notifications',
          'feature_requests')
MARKER = 'sqlite-to-postgres-v1'


def digest_rows(rows):
    digest = hashlib.sha256()
    count = 0
    for row in rows:
        digest.update(json.dumps(list(row), ensure_ascii=False, separators=(',', ':')).encode())
        digest.update(b'\n')
        count += 1
    return count, digest.hexdigest()


def migrate(source_path, config):
    initialize_postgres(config)
    path = Path(source_path)
    with connect(config) as target:
        target.execute('SELECT pg_advisory_xact_lock(734521002)')
        if target.execute('SELECT 1 FROM app_migrations WHERE name=?', (MARKER,)).fetchone():
            return False
        for table in TABLES:
            if target.execute('SELECT 1 FROM ' + table + ' LIMIT 1').fetchone():
                raise RuntimeError('Target contains records without a migration marker; refusing to overwrite it')
        if path.exists():
            source = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                source.execute('BEGIN')  # consistent read snapshot
                available = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                unknown = available - set(TABLES) - {'sqlite_sequence'}
                if unknown:
                    raise RuntimeError('Unknown source tables; migration stopped: ' + ', '.join(sorted(unknown)))
                for table in TABLES:
                    if table not in available:
                        continue
                    info = list(source.execute('PRAGMA table_info(' + table + ')'))
                    columns = [row[1] for row in info]
                    primary = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]]
                    order = primary or columns
                    column_sql = sql.SQL(',').join(map(sql.Identifier, columns))
                    ordered = sql.SQL('SELECT {} FROM {} ORDER BY {}').format(
                        column_sql, sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, order)))
                    select_sql = 'SELECT ' + ','.join('"' + col + '"' for col in columns) + ' FROM ' + table + ' ORDER BY ' + ','.join('"' + col + '"' for col in order)
                    insert_sql = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
                        sql.Identifier(table), column_sql, sql.SQL(',').join(sql.Placeholder() for _ in columns))
                    cursor = source.execute(select_sql)
                    while batch := cursor.fetchmany(500):
                        target.raw.cursor().executemany(insert_sql, batch)
                    expected = digest_rows(source.execute(select_sql))
                    with target.raw.cursor(row_factory=tuple_row) as cursor:
                        cursor.execute(ordered)
                        actual = digest_rows(cursor)
                    if actual != expected:
                        raise RuntimeError('Record verification failed: ' + table)
                    if 'id' in columns:
                        sequence = target.raw.execute('SELECT pg_get_serial_sequence(%s, %s)', (table, 'id')).fetchone()[0]
                        if sequence:
                            maximum = target.raw.execute(sql.SQL('SELECT MAX(id) FROM {}').format(sql.Identifier(table))).fetchone()[0]
                            target.raw.execute('SELECT setval(%s, %s, %s)', (sequence, maximum or 1, maximum is not None))
            finally:
                source.close()
        target.execute('INSERT INTO app_migrations(name) VALUES(?)', (MARKER,))
    return True


if __name__ == '__main__':
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise SystemExit('DATABASE_URL is required')
    source = os.environ.get('DATABASE_PATH', '/var/lib/parenting-together/parenting.db')
    changed = migrate(source, {'DATABASE_URL': url})
    print('PostgreSQL copy verified.' if changed else 'PostgreSQL migration already completed.')
