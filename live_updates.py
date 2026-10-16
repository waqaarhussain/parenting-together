"""One PostgreSQL LISTEN connection per worker, shared by its SSE subscribers."""
import json
import logging
import queue
import threading
import time
from collections import Counter

import psycopg

log = logging.getLogger(__name__)


class LiveHub:
    def __init__(self, database_url, maintenance=None, max_subscribers=96):
        self.database_url = database_url
        self.maintenance = maintenance
        self.max_subscribers = max_subscribers
        self.lock = threading.Lock()
        self.clients = {}
        self.thread = None
        self.ready = threading.Event()

    def subscribe(self, family_id, user_id):
        with self.lock:
            if len(self.clients) >= self.max_subscribers:
                return None
            if Counter(user for _, user in self.clients.values())[user_id] >= 3:
                return None
            channel = queue.Queue(maxsize=1)
            self.clients[channel] = (family_id, user_id)
            if self.thread is None:
                self.thread = threading.Thread(target=self.listen, daemon=True, name='family-events')
                self.thread.start()
        return channel

    def unsubscribe(self, channel):
        with self.lock:
            self.clients.pop(channel, None)

    def publish(self, payload):
        with self.lock:
            clients = list(self.clients.items())
        for channel, (family_id, _) in clients:
            if payload.get('family_id') not in (None, family_id):
                continue
            # Coalesce bursts to a single invalidation. Every refresh fetches the
            # current authorized state, so no event replay log or plaintext is needed.
            try:
                channel.put_nowait({'changed': True, 'tables': [payload.get('table', 'all')]})
            except queue.Full:
                try:
                    previous = channel.get_nowait()
                except queue.Empty:
                    previous = {'tables': []}
                combined = set(previous['tables']) | {payload.get('table', 'all')}
                try:
                    channel.put_nowait({'changed': True, 'tables': sorted(combined)})
                except queue.Full:
                    pass

    def listen(self):
        last_maintenance = 0
        while True:
            try:
                with psycopg.connect(self.database_url, autocommit=True, connect_timeout=10) as conn:
                    conn.execute('LISTEN parenting_live')
                    self.ready.set()
                    self.publish({'family_id': None})  # catch up after a reconnect
                    while True:
                        for notification in conn.notifies(timeout=1, stop_after=64):
                            self.publish(json.loads(notification.payload))
                        if time.monotonic() - last_maintenance >= 15:
                            last_maintenance = time.monotonic()
                            with self.lock:
                                active = set(self.clients.values())
                            if self.maintenance and active:
                                try:
                                    self.maintenance(active)
                                except Exception:
                                    log.exception('Live reminder maintenance failed')
            except Exception:
                self.ready.clear()
                log.exception('Live listener disconnected; reconnecting')
                time.sleep(3)
