#!/usr/bin/env python3
"""軽量APIサーバー: アカウントステータス更新用（Streamlitリロード不要に）"""
import os, sqlite3, json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'instagram_dm.db')

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/action':
            params = parse_qs(parsed.query)
            action = params.get('action', [None])[0]
            aid = params.get('aid', [None])[0]

            if action in ('sent', 'skipped') and aid:
                try:
                    conn = sqlite3.connect(DB_PATH)
                    if action == 'sent':
                        conn.execute(
                            "UPDATE accounts SET status='sent', sent_at=? WHERE id=?",
                            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), int(aid))
                        )
                    else:
                        conn.execute(
                            "UPDATE accounts SET status='skipped' WHERE id=?",
                            (int(aid),)
                        )
                    conn.commit()
                    conn.close()
                    self._json(200, {'ok': True})
                except Exception as e:
                    self._json(500, {'ok': False, 'error': str(e)})
            else:
                self._json(400, {'ok': False, 'error': 'bad params'})
        else:
            self._json(404, {'ok': False})

    def _json(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass  # suppress logs

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', 8502), Handler)
    print('API server on :8502')
    server.serve_forever()
