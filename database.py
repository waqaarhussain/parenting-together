"""Small database boundary; SQLite remains available for development and rollback."""
import os
import re
import sqlite3
import threading
from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool

IntegrityError = (sqlite3.IntegrityError, psycopg.IntegrityError)
SERIAL_TABLES = {'users', 'families', 'children', 'messages', 'events', 'handovers',
                 'decisions', 'expenses', 'rules', 'audit', 'notifications', 'feature_requests'}
_pools = {}
_pool_lock = threading.Lock()


class Row(dict):
    """Support named columns and count()[0], matching the existing SQLite API."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def row_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: Row(zip(names, values))


def is_postgres(config):
    return bool(config.get('DATABASE_URL'))


def get_pool(config):
    key = (os.getpid(), config['DATABASE_URL'])
    with _pool_lock:
        if key not in _pools:
            _pools[key] = ConnectionPool(
                conninfo=key[1], min_size=1, max_size=int(config.get('DB_POOL_SIZE', 8)),
                timeout=10, open=True, kwargs={'row_factory': row_factory, 'connect_timeout': 10},
                check=ConnectionPool.check_connection,
            )
        return _pools[key]


def parameter_sql(sql):
    # Only qmarks outside SQL strings are parameters. Literal percent signs must
    # be escaped for psycopg's binding even inside quoted SQL strings.
    result, quoted, index = [], False, 0
    while index < len(sql):
        char = sql[index]
        if char == "'":
            if quoted and index + 1 < len(sql) and sql[index + 1] == "'":
                result.append("''")
                index += 2
                continue
            quoted = not quoted
        result.append('%s' if char == '?' and not quoted else '%%' if char == '%' else char)
        index += 1
    return ''.join(result)


class Cursor:
    def __init__(self, cursor, lastrowid=None):
        self.cursor, self.lastrowid = cursor, lastrowid
    def fetchone(self):
        return self.cursor.fetchone()
    def fetchall(self):
        return self.cursor.fetchall()
    def __iter__(self):
        return iter(self.cursor)
    @property
    def rowcount(self):
        return self.cursor.rowcount


class Connection:
    def __init__(self, config):
        self.postgres = is_postgres(config)
        self.pool = get_pool(config) if self.postgres else None
        self.raw = self.pool.getconn() if self.pool else sqlite3.connect(config['DATABASE_PATH'], timeout=15)
        if not self.postgres:
            self.raw.row_factory = sqlite3.Row
            self.raw.execute('PRAGMA foreign_keys = ON')
            self.raw.execute('PRAGMA journal_mode = WAL')
    def __enter__(self):
        return self
    def __exit__(self, kind, value, traceback):
        try:
            self.raw.rollback() if kind else self.raw.commit()
        except BaseException:
            self.raw.rollback()
            raise
        finally:
            if self.pool:
                self.pool.putconn(self.raw)
            else:
                self.raw.close()
    def execute(self, sql, params=None):
        if not self.postgres:
            return self.raw.execute(sql, params or ())
        insert = re.match(r'\s*INSERT\s+INTO\s+(\w+)\s*\(', sql, re.I)
        returning = bool(insert and insert[1].lower() in SERIAL_TABLES and 'RETURNING' not in sql.upper())
        if returning:
            sql = sql.rstrip().rstrip(';') + ' RETURNING id'
        cursor = self.raw.execute(parameter_sql(sql), params) if params is not None else self.raw.execute(sql)
        row = cursor.fetchone() if returning else None
        return Cursor(cursor, row['id'] if row else None)
    def executemany(self, sql, values):
        if not self.postgres:
            return self.raw.executemany(sql, values)
        cursor = self.raw.cursor()
        cursor.executemany(parameter_sql(sql), values)
        return Cursor(cursor)
    def executescript(self, sql):
        if self.postgres:
            return self.raw.execute(sql, prepare=False)
        return self.raw.executescript(sql)


def connect(config):
    return Connection(config)


def lock_family(conn, family_id):
    if conn.postgres:
        conn.execute('SELECT id FROM families WHERE id=? FOR UPDATE', (family_id,)).fetchone()
    elif not conn.raw.in_transaction:
        conn.execute('BEGIN IMMEDIATE')


def initialize_postgres(config):
    with connect(config) as conn:
        # Serialize schema setup across workers/repeated installer invocations.
        conn.execute('SELECT pg_advisory_xact_lock(734521001)')
        conn.executescript(Path(__file__).with_name('schema_postgres.sql').read_text())
