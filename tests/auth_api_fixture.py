"""Only for private test namespaces; serves the approved auth-dir scalar."""
import json,os
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
class Handler(BaseHTTPRequestHandler):
 def log_message(self,format,*args):pass
 def do_GET(self):
  self.send_response(200);self.end_headers()
  value='/srv/changed-auth' if os.environ.get('CASE')=='changed_auth' else '/srv/actual-auth'
  self.wfile.write(json.dumps(value).encode())
server=HTTPServer(('127.0.0.1',8317),Handler)
Path('/run/auth-fixture-ready').touch()
server.serve_forever()
