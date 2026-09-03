#!/usr/bin/env python3
import json, subprocess, sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parent
class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/latest'):
            p=ROOT/'runtime/latest.json'; data=json.loads(p.read_text()) if p.exists() else {}
            self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8'); self.end_headers(); self.wfile.write(json.dumps(data,ensure_ascii=False).encode()); return
        super().do_GET()
    def do_POST(self):
        if self.path != '/api/refresh': self.send_error(404); return
        n=int(self.headers.get('content-length','0')); body=json.loads(self.rfile.read(n) or '{}'); q=body.get('quarter','全年')
        p=subprocess.run([sys.executable,str(ROOT/'refresh.py'),'--quarter',q],cwd=ROOT.parent,text=True,capture_output=True)
        self.send_response(200 if p.returncode==0 else 500); self.send_header('Content-Type','application/json; charset=utf-8'); self.end_headers(); self.wfile.write((p.stdout if p.returncode==0 else json.dumps({'error':p.stderr},ensure_ascii=False)).encode())
if __name__=='__main__': ThreadingHTTPServer(('127.0.0.1',8787),Handler).serve_forever()
