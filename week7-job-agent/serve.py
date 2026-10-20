"""The Job Agent page on this computer.

  uv run serve.py [--port 8765] [--no-open]

Serves console.html at http://localhost:8765 and gives it the local database, work/db, through a
small JSON API. The page works as it does in the cloud; Run now and Suggest changes start
`run.py` here instead of a scheduled task. A finished run's results are written into work/db
when the server starts, if a run left any behind (work/out/writes.json).

  GET  /db/rev                      a number that grows on every change; the page polls it
  GET  /db/<collection>             every document: [{"id", "data", "version"}]
  GET  /db/<collection>/<id>        one document
  PUT  /db/<collection>/<id>        set {"data": ...}; DELETE removes it
  POST /run {"kind": "run"|"suggest"}   starts `run.py local manual` or `run.py suggest`
  GET  /run                         the running job's state and its last log lines
"""

import json
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import dbio
import localdb

HERE = Path(__file__).parent
PAGE = HERE / "console.html"
JOB = {"proc": None, "kind": None, "log": [], "started": None}


def start_job(kind):
    if JOB["proc"] and JOB["proc"].poll() is None:
        return False
    cmd = [sys.executable, str(HERE / "run.py")] + (["local", "manual"] if kind == "run" else ["suggest"])
    JOB.update(proc=subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True),
               kind=kind, log=[], started=dbio.datetime.now(dbio.timezone.utc).isoformat())
    threading.Thread(target=pump, daemon=True).start()
    return True


def pump():
    p = JOB["proc"]
    for line in p.stdout:
        line = line.rstrip()
        JOB["log"].append(line)
        print("  " + line, flush=True)
        del JOB["log"][:-200]
    p.wait()
    JOB["log"].append(f"[exit {p.returncode}]")
    localdb.update("meta/request", {"status": "done"})
    localdb.bump()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):      # quiet
        pass

    def send(self, code, body=None, ctype="application/json"):
        data = (json.dumps(body) if ctype == "application/json" else body).encode() if body is not None else b""
        self.send_response(code)
        self.send_header("content-type", ctype + "; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("content-length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            html = PAGE.read_text().replace("<script>", "<script>window.JOB_AGENT_LOCAL = true;</script><script>", 1)
            return self.send(200, html, "text/html")
        if p == "/db/rev":
            return self.send(200, {"rev": localdb.rev()})
        if p == "/run":
            proc = JOB["proc"]
            return self.send(200, {"running": bool(proc and proc.poll() is None), "kind": JOB["kind"], "started": JOB["started"], "log": JOB["log"][-40:]})
        if p.startswith("/db/"):
            try:
                parts = localdb.check(p[4:])
                if len(parts) % 2:
                    return self.send(200, localdb.list_docs("/".join(parts)))
                d = localdb.read("/".join(parts))
                return self.send(200 if d else 404, d or {"error": "not found"})
            except ValueError as e:
                return self.send(400, {"error": str(e)})
        self.send(404, {"error": "not found"})

    def do_PUT(self):
        p = self.path.split("?")[0]
        if not p.startswith("/db/"):
            return self.send(404, {"error": "not found"})
        try:
            b = self.body()
            v = localdb.write(p[4:], b.get("data", {}), b.get("if_version"))
            self.send(200, {"version": v})
        except ValueError as e:
            self.send(409 if "version" in str(e) else 400, {"error": str(e)})

    def do_DELETE(self):
        p = self.path.split("?")[0]
        if not p.startswith("/db/"):
            return self.send(404, {"error": "not found"})
        try:
            self.send(200, {"deleted": localdb.delete(p[4:])})
        except ValueError as e:
            self.send(400, {"error": str(e)})

    def do_POST(self):
        p = self.path.split("?")[0]
        if p == "/run":
            kind = self.body().get("kind", "run")
            if kind not in ("run", "suggest"):
                return self.send(400, {"error": "kind must be run or suggest"})
            localdb.write("meta/request", {"kind": kind, "status": "started", "requested_at": dbio.datetime.now(dbio.timezone.utc).isoformat()})
            ok = start_job(kind)
            return self.send(200 if ok else 409, {"started": ok, "error": None if ok else "a run is already going"})
        self.send(404, {"error": "not found"})


def main(argv):
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8765
    dbio.seed()
    if (dbio.WORK / "out" / "writes.json").exists():
        dbio.apply()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://localhost:{port}"
    print(f"Job Agent at {url}  (database: work/db, Ctrl-C to stop)")
    if "--no-open" not in argv:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
