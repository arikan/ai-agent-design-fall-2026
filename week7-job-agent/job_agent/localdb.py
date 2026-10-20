"""The artifact's database, as files on this computer: work/db/<collection>/<id>.json.

The cloud run reads the artifact's database into the same files (ArtifactData with out_dir),
so the engine never knows the difference. serve.py serves these files to the page, and
dbio.apply writes a run's results into them.

A document file holds {"data": ..., "version": n}. A path with an even number of segments is a
document (agent/current, meta/progress); with an odd number, a collection (matches,
agent/current/versions).
"""

import json
import re
import threading
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "work" / "db"
SAFE = re.compile(r"^[A-Za-z0-9_\-.~:@+]{1,200}$")
_lock = threading.Lock()
_rev = [0]


def check(path):
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts or any(not SAFE.match(p) or p in (".", "..") for p in parts):
        raise ValueError(f"bad path {path!r}")
    return parts


def doc_file(path):
    parts = check(path)
    if len(parts) % 2:
        raise ValueError(f"{path!r} is a collection, not a document")
    return DB.joinpath(*parts[:-1]) / f"{parts[-1]}.json"


def read(path):
    f = doc_file(path)
    if not f.exists():
        return None
    d = json.loads(f.read_text())
    return d if isinstance(d, dict) and "data" in d else {"data": d, "version": 1}


def write(path, data, version=None):
    """Set a document. Returns the new version."""
    f = doc_file(path)
    with _lock:
        cur = read(path)
        if version is not None and cur and cur["version"] != version:
            raise ValueError(f"{path}: version is {cur['version']}, not {version}")
        new = (cur["version"] + 1) if cur else 1
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"data": data, "version": new}, indent=1))
        _rev[0] += 1
    return new


def update(path, patch):
    cur = read(path)
    data = dict(cur["data"]) if cur else {}
    data.update(patch)
    return write(path, data)


def delete(path):
    f = doc_file(path)
    with _lock:
        if f.exists():
            f.unlink()
            _rev[0] += 1
            return True
    return False


def list_docs(path):
    parts = check(path)
    if len(parts) % 2 == 0:
        raise ValueError(f"{path!r} is a document, not a collection")
    d = DB.joinpath(*parts)
    out = []
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        raw = json.loads(f.read_text())
        doc = raw if isinstance(raw, dict) and "data" in raw else {"data": raw, "version": 1}
        out.append({"id": f.stem, "data": doc["data"], "version": doc["version"]})
    return out


def rev():
    """Changes made by this process, plus the newest file time, so a run in another process
    (cron, or `job-agent run` in a terminal) also shows up on an open page."""
    newest = max((p.stat().st_mtime_ns for p in DB.rglob("*.json")), default=0) if DB.exists() else 0
    return f"{_rev[0]}-{newest}-{sum(1 for _ in DB.rglob('*.json')) if DB.exists() else 0}"


def bump():
    with _lock:
        _rev[0] += 1
