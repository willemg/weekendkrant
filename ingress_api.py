"""Lokale HTTP-producerinterface voor de persistente ingressqueue."""
import argparse
from contextlib import closing
from dataclasses import dataclass, field
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sqlite3

from ingress_queue import IngressQueue
from sherlock_state import SherlockState


class PayloadTooLarge(Exception):
    pass


@dataclass(frozen=True)
class Config:
    token: str = field(repr=False)
    db_path: Path = Path('/home/weekendkrant/weekendkrant.sqlite3')
    host: str = '127.0.0.1'
    port: int = 8000

    def __post_init__(self):
        if not self.token:
            raise ValueError('WEEKENDKRANT_INGRESS_TOKEN ontbreekt of is leeg')

    @classmethod
    def from_environment(cls, argv=None):
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--host', default='127.0.0.1')
        parser.add_argument('--port', type=int, default=8000)
        parser.add_argument('--db', type=Path, default=cls.db_path)
        args = parser.parse_args(argv)
        return cls(token=os.environ.get('WEEKENDKRANT_INGRESS_TOKEN', ''),
                   db_path=args.db, host=args.host, port=args.port)


def create_server(config):
    queue = IngressQueue(config.db_path)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, format, *args):
            # Geen requestheaders, payloads of secrets in standaard HTTP-logs.
            pass

        def reply(self, status, body):
            data = json.dumps(body).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            if status == 401:
                self.send_header('WWW-Authenticate', 'Bearer')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path != '/health':
                self.reply(404, {'error': 'not_found'})
                return
            try:
                count = queue.pending_count()
            except sqlite3.Error:
                self.reply(503, {'error': 'queue_unavailable'})
                return
            self.reply(200, {'status': 'ok', 'pending': count})

        def do_POST(self):
            routes = {'/ingress', '/sherlock/runs', '/sherlock/sources/filter',
                      '/sherlock/sources', '/sherlock/runs/finish'}
            if self.path not in routes:
                self.reply(404, {'error': 'not_found'})
                return
            authorization = self.headers.get('Authorization', '')
            expected = 'Bearer ' + config.token
            if not hmac.compare_digest(authorization.encode('utf-8'), expected.encode('utf-8')):
                self.reply(401, {'error': 'unauthorized'})
                return
            try:
                payload = self.read_json()
            except PayloadTooLarge:
                self.reply(413, {'error': 'payload_too_large'})
                return
            except (ValueError, TypeError, UnicodeError, RecursionError):
                self.reply(400, {'error': 'invalid_json_object'})
                return
            if self.path == '/ingress':
                try:
                    item_id = queue.add(payload)
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    self.reply(400, {'error': 'invalid_json_object'})
                    return
                except sqlite3.Error:
                    self.reply(503, {'error': 'queue_unavailable'})
                    return
                self.reply(201, {'id': item_id})
                return

            try:
                self.handle_sherlock(payload)
            except sqlite3.IntegrityError:
                self.reply(409, {'error': 'source_conflict'})
            except sqlite3.Error:
                self.reply(503, {'error': 'database_unavailable'})
            except ValueError as error:
                message = str(error)
                if message in ('Onbekende of reeds afgesloten run',
                               'Bron vereist een running run met hetzelfde topic'):
                    self.reply(409, {'error': 'run_conflict'})
                else:
                    self.reply(400, {'error': 'invalid_request'})

        def read_json(self):
            # Shared ingress limits: no chunked bodies, bounded reads, socket timeout.
            if self.headers.get('Transfer-Encoding') is not None:
                raise ValueError('Unsupported transfer encoding')
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                raise ValueError('Invalid Content-Length')
            length = int(lengths[0])
            if length > 1024 * 1024:
                raise PayloadTooLarge()
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('Incomplete body')
            def reject_constant(value):
                raise ValueError('Invalid JSON constant')
            payload = json.loads(raw.decode('utf-8'), parse_constant=reject_constant)
            if not isinstance(payload, dict):
                raise ValueError('Expected JSON object')
            return payload

        def handle_sherlock(self, payload):
            def schema(required, optional=()):
                if set(payload) - set(required) - set(optional) or not set(required) <= set(payload):
                    raise ValueError('Invalid request fields')
            with closing(sqlite3.connect(config.db_path, timeout=5)) as db:
                state = SherlockState(db)
                if self.path == '/sherlock/runs':
                    schema(set())
                    run_id, topic = state.start_next_run()
                    self.reply(201, {'run_id': run_id, 'topic': topic})
                elif self.path == '/sherlock/sources/filter':
                    schema({'urls'})
                    urls = state.filter_unreviewed(payload['urls'])
                    self.reply(200, {'unreviewed': urls})
                elif self.path == '/sherlock/sources':
                    schema({'run_id', 'topic', 'url', 'outcome', 'rationale'}, {'title'})
                    canonical = state.record_reviewed_source(
                        payload['run_id'], payload['topic'], payload['url'],
                        payload['outcome'], payload['rationale'], payload.get('title'))
                    self.reply(201, {'canonical_url': canonical})
                else:
                    schema({'run_id', 'status'})
                    state.finish_run(payload['run_id'], payload['status'])
                    self.reply(200, {'run_id': payload['run_id'], 'status': payload['status']})

    return HTTPServer((config.host, config.port), Handler)


def main(argv=None):
    try:
        config = Config.from_environment(argv)
    except ValueError as error:
        raise SystemExit(str(error))
    with create_server(config) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
