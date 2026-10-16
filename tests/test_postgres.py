"""Run the same feature flows on real PostgreSQL, plus migration and live tests."""
import concurrent.futures
import os
import queue
import sqlite3
import time
import unittest
from pathlib import Path

import psycopg
from psycopg import sql
import test_flows
from app import app, db, init_db
from database import connect, initialize_postgres, parameter_sql
from live_updates import LiveHub
from migrate_sqlite import TABLES, migrate

URL = os.environ.get('PG_TEST_URL', '')


class SQLBinding(unittest.TestCase):
    def test_literal_question_marks_percent_and_quotes(self):
        self.assertEqual(parameter_sql("SELECT '?' AS a, 'can''t?' AS b WHERE x=? AND y LIKE 'pt1:%'"),
                         "SELECT '?' AS a, 'can''t?' AS b WHERE x=%s AND y LIKE 'pt1:%%'")


@unittest.skipUnless(URL, 'PG_TEST_URL is required for real PostgreSQL integration tests')
class PostgresFlows(test_flows.TwoParentFlow):
    def setUp(self):
        app.config['DATABASE_URL'] = ''
        super().setUp()
        self.sqlite_path = app.config['DATABASE_PATH']
        self.config = {'DATABASE_URL': URL}
        initialize_postgres(self.config)
        with psycopg.connect(URL) as conn:
            conn.execute(sql.SQL('TRUNCATE {} RESTART IDENTITY CASCADE').format(
                sql.SQL(',').join(map(sql.Identifier, (*TABLES, 'app_migrations')))))
        app.config['DATABASE_URL'] = URL

    def tearDown(self):
        app.config['DATABASE_URL'] = ''
        super().tearDown()

    def test_migration_preserves_ciphertext_ids_hashes_and_is_repeatable(self):
        app.config['DATABASE_URL'] = ''
        first = self.register(self.first, 'Parent One', 'one@example.test')
        envelope = {'v': 2, 'salt': 'salt', 'iv': 'iv', 'data': 'ciphertext-envelope'}
        sent = self.post(self.first, first['csrf'], '/api/messages', {'body': 'pt1:opaque-iv:ciphertext'})
        self.assertEqual(sent.status_code, 201)
        self.post(self.first, first['csrf'], '/api/vault/setup', {'envelope': envelope, 'records': []})
        message_id, message_hash = sent.json['id'], sent.json['hash']
        self.assertTrue(migrate(self.sqlite_path, self.config))
        self.assertFalse(migrate(self.sqlite_path, self.config))
        app.config['DATABASE_URL'] = URL
        with db() as conn:
            row = conn.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone()
            self.assertEqual(row['body'], 'pt1:opaque-iv:ciphertext')
            self.assertEqual(row['record_hash'], message_hash)
        self.assertTrue(self.first.get('/api/messages/verify').json['verified'])
        self.assertEqual(self.first.get('/api/me').json['vault_envelope'], envelope)
        next_message = self.post(self.first, first['csrf'], '/api/messages', {'body': 'pt1:next:cipher'})
        self.assertGreater(next_message.json['id'], message_id)
        self.assertTrue(self.first.get('/api/messages/verify').json['verified'])
        login = self.first.post('/api/auth/login', json={'identifier': 'ONE@EXAMPLE.TEST', 'password': 'sample-password-123'})
        self.assertEqual(login.status_code, 200)

    def test_failed_import_rolls_back_and_does_not_mark_complete(self):
        source = Path(self.tmp.name) / 'bad.db'
        with sqlite3.connect(source) as conn:
            conn.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT, password_hash TEXT, created_at TEXT)')
            conn.execute("INSERT INTO users VALUES(1,'A','same@example.test','hash','stamp')")
            conn.execute("INSERT INTO users VALUES(2,'B','SAME@example.test','hash','stamp')")
        with self.assertRaises(psycopg.IntegrityError):
            migrate(source, self.config)
        with db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM users').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM app_migrations').fetchone()[0], 0)

    def test_nonempty_target_is_never_overwritten(self):
        self.register(self.first, 'Parent One', 'one@example.test')
        with self.assertRaisesRegex(RuntimeError, 'refusing to overwrite'):
            migrate(self.sqlite_path, self.config)
        self.assertEqual(self.first.get('/api/me').json['user']['email'], 'one@example.test')

    def test_concurrent_messages_preserve_the_chain(self):
        first = self.register(self.first, 'Parent One', 'one@example.test')
        uid = first['user']['id']
        def send(index):
            client = app.test_client()
            with client.session_transaction() as session:
                session['user_id'], session['csrf'] = uid, 'concurrency-test'
            return self.post(client, 'concurrency-test', '/api/messages', {'body': 'concurrent ' + str(index)}).status_code
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            self.assertEqual(list(executor.map(send, range(24))), [201] * 24)
        verified = self.first.get('/api/messages/verify').json
        self.assertTrue(verified['verified'])
        self.assertEqual(verified['count'], 24)

    def test_append_only_protection_survives_vault_migration(self):
        first = self.register(self.first, 'Parent One', 'one@example.test')
        sent = self.post(self.first, first['csrf'], '/api/messages', {'body': 'original'}).json
        for query in ['UPDATE messages SET body=\'changed\' WHERE id=?', 'DELETE FROM messages WHERE id=?']:
            with self.assertRaises(psycopg.errors.CheckViolation):
                with db() as conn:
                    conn.execute(query, (sent['id'],))
        self.assertTrue(self.first.get('/api/messages/verify').json['verified'])

    def test_live_updates_are_committed_family_scoped_and_coalesced(self):
        first = self.register(self.first, 'Parent One', 'one@example.test')
        second = self.register(self.second, 'Other Family', 'other@example.test')
        hub = LiveHub(URL)
        channel = hub.subscribe(first['family']['id'], first['user']['id'])
        other = hub.subscribe(second['family']['id'], second['user']['id'])
        self.assertTrue(hub.ready.wait(10))
        time.sleep(.1)
        for q in [channel, other]:
            while not q.empty(): q.get_nowait()
        with db() as conn:
            conn.execute('INSERT INTO typing_status(family_id,user_id,expires_at) VALUES(?,?,?)',
                         (first['family']['id'], first['user']['id'], int(time.time())+6))
        self.assertTrue(channel.get(timeout=5)['changed'])
        self.assertTrue(other.empty())
        with self.assertRaises(ValueError):
            with db() as conn:
                conn.execute('DELETE FROM typing_status WHERE family_id=?', (first['family']['id'],))
                raise ValueError('rollback')
        with self.assertRaises(queue.Empty): channel.get(timeout=.3)
        # Many changes queue one refresh rather than unbounded event history.
        for _ in range(1000): hub.publish({'family_id':first['family']['id']})
        self.assertEqual(channel.qsize(), 1)
        hub.unsubscribe(channel);hub.unsubscribe(other)

    def test_sse_requires_login_and_releases_subscription(self):
        self.assertEqual(self.first.get('/api/live').status_code, 401)
        first = self.register(self.first, 'Parent One', 'one@example.test')
        response = self.first.get('/api/live', buffered=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'text/event-stream')
        ready = next(iter(response.response))
        self.assertIn(b'event: ready', ready)
        self.assertNotIn(first['user']['email'].encode(), ready)
        response.close()

    def test_full_family_database_migrates_and_keeps_both_logins(self):
        app.config['DATABASE_URL'] = ''
        self.test_join_and_shared_features()
        self.assertTrue(migrate(self.sqlite_path, self.config))
        app.config['DATABASE_URL'] = URL
        self.assertEqual(self.first.get('/api/me').json['user']['email'], 'one@example.test')
        self.assertEqual(self.second.get('/api/me').json['user']['email'], 'two@example.test')
        self.assertTrue(self.first.get('/api/messages/verify').json['verified'])
        self.assertEqual(len(self.second.get('/api/events').json), 1)
        self.assertEqual(self.second.get('/api/handovers').json[0]['status'], 'completed')
        self.assertEqual(len(self.second.get('/api/rules').json), 1)
