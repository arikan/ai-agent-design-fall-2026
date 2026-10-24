"""The Job Agent page on this computer.

  uv run jobagent serve [--port 8765] [--no-open]

Serves console.html at http://localhost:8765 and gives it the local database, work/db, through a
small JSON API. The page works as it does in the cloud; Run now and Suggest changes start
`run.py` here instead of a scheduled task. A finished run's results are written into work/db
when the server starts, if a run left any behind (work/out/writes.json).

  GET  /db/rev                      a number that grows on every change; the page polls it
  GET  /db/<collection>             every document: [{"id", "data", "version"}]
  GET  /db/<collection>/<id>        one document
  PUT  /db/<collection>/<id>        set {"data": ...}; DELETE removes it
  POST /run {"kind": "run"|"suggest"|"test"|"figure"|"find", "source_id"?|"url"?|"name"?}
                                    starts a run, suggestions, one source's test, or working out a source from an address
  POST /probe {"name": "Cycles"}    which job boards a company name finds
  GET  /run                         the running job's state and its last log lines
"""

import json
import re
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import dbio
from . import localdb

HERE = Path(__file__).resolve().parents[1]     # the project folder: work/, defaults/, caps.json
PAGE = HERE / "console.html"
JOB = {"proc": None, "kind": None, "log": [], "started": None}


def start_job(kind, source_id=None):
    if JOB["proc"] and JOB["proc"].poll() is None:
        return False
    if kind == "test":          # one source, as RUN.md's "Test one source" does it in the cloud
        agent = (localdb.read("agent/current") or {}).get("data", {})
        src = next((x for x in agent.get("sources", []) if x["id"] == source_id), None)
        doc = f"source_tests/{safe(source_id)}"
        if not src:
            localdb.write(doc, {"source_id": source_id, "status": "not_found", "finished_at": now()})
            return True
        (dbio.WORK).mkdir(exist_ok=True)
        (dbio.WORK / "test-source.json").write_text(json.dumps(src))
        cmd = [sys.executable, "-u", "-m", "jobagent", "sources", "try", "work/test-source.json", "work/test-result.json"]
    elif kind == "figure":
        (dbio.WORK / "figure-result.json").unlink(missing_ok=True)
        localdb.write("meta/figure", {"url": source_id, "status": "working", "started_at": now()})
        cmd = [sys.executable, "-u", "-m", "jobagent", "figure", source_id]
    elif kind == "find":
        (dbio.WORK / "find-result.json").unlink(missing_ok=True)
        localdb.write("meta/figure", {"url": "name:" + source_id, "status": "working", "started_at": now()})
        cmd = [sys.executable, "-u", "-m", "jobagent", "find", source_id]
    else:
        cmd = [sys.executable, "-u", "-m", "jobagent"] + (["run", "manual"] if kind == "run" else ["suggest"])
    JOB.update(proc=subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1),
               kind=kind, source_id=source_id, log=[], started=now())
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
    if JOB["kind"] in ("figure", "find"):
        r = dbio.read(dbio.WORK / f"{JOB['kind']}-result.json") or {"url": JOB["source_id"] if JOB["kind"] == "figure" else "name:" + JOB["source_id"], "how": "the step did not finish"}
        src = r.get("source")
        if src:
            v = dbio.add_source(src, f"Added {src['id']} from {r['url']}")
            localdb.write(f"source_tests/{safe(src['id'])}", {"source_id": src["id"], "status": "done", "health": {"status": "ok", "fetched": None, "kept": int(re.search(r"(\d+) posts", r["how"] or "").group(1)) if re.search(r"(\d+) posts", r["how"] or "") else None}, "finished_at": now()})
            r["version"] = v
        localdb.write("meta/figure", {**r, "status": "done", "finished_at": now()})
    if JOB["kind"] == "test":
        doc = f"source_tests/{safe(JOB['source_id'])}"
        cur = (localdb.read(doc) or {}).get("data", {})
        result = dbio.read(dbio.WORK / "test-result.json") or {"health": {"status": "failed", "error": "the test did not finish"}}
        localdb.write(doc, {**result, "source_id": JOB["source_id"], "status": "done", "requested_at": cur.get("requested_at"), "finished_at": now()})
    localdb.update("meta/request", {"status": "done"})
    localdb.bump()


def now():
    return dbio.datetime.now(dbio.timezone.utc).isoformat()


def safe(source_id):
    return dbio.safe(source_id)


from .boards import BOARDS, probe     # noqa: E402  (moved; also used by suggestions)


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
            b = self.body()
            kind = b.get("kind", "run")
            if kind not in ("run", "suggest", "test", "figure", "find"):
                return self.send(400, {"error": "kind must be run, suggest, test, figure or find"})
            what = b.get("url") if kind == "figure" else b.get("name") if kind == "find" else b.get("source_id")
            localdb.write("meta/request", {"kind": kind, "status": "started", "requested_at": now(), **({"source_id": what} if what else {})})
            ok = start_job(kind, what)
            return self.send(200 if ok else 409, {"started": ok, "error": None if ok else "a run is already going"})
        if p == "/probe":
            name = str(self.body().get("name", ""))[:80]
            return self.send(200, {"found": probe(name) if name.strip() else []})
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
