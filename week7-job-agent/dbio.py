"""Bridge between the artifact database and the engine's files.

The engine cannot reach the database; the Claude session can. The session saves
database reads as JSON files under work/db/ (ArtifactData with out_dir), then:

  uv run dbio.py config   -> work/config.json from work/db/
  uv run dbio.py export   -> work/out/*.json plus work/out/writes.json, a ready batch
                              for the session to write back with ArtifactData
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
WORK = HERE / "work"


def body(path):
    d = json.loads(path.read_text())
    return d.get("data", d)


def config():
    db = WORK / "db"
    searches = []
    for p in sorted((db / "searches").glob("*.json")):
        s = body(p)
        s["id"] = p.stem
        searches.append(s)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    runs_today = sum(1 for p in (db / "runs").glob("*.json")
                     if p.stem.startswith(f"run-{today}") and body(p).get("status") == "ok") if (db / "runs").exists() else 0
    # Postings already matched for a search are not judged again: only new ones cost a judgment,
    # and every database write stays a create.
    seen = {}
    for p in (db / "matches").glob("*.json") if (db / "matches").exists() else []:
        m = body(p)
        seen.setdefault(m["search_id"], []).append(m["posting_id"])
    cfg = {"runs_today": runs_today, "agent": body(db / "agent" / "current.json"), "searches": searches, "seen": seen}
    (WORK / "config.json").write_text(json.dumps(cfg, indent=2))
    print(f"config: {len(searches)} search(es), agent v{cfg['agent']['version']}, {runs_today} run(s) already today")


def safe(source_id):
    import re
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", source_id)


def export():
    r = json.loads((WORK / "results.json").read_text())
    out = WORK / "out"
    out.mkdir(exist_ok=True)
    writes = []
    run_path = out / "run.json"
    run_path.write_text(json.dumps(r["run"]))
    writes.append({"op": "set", "collection": "runs", "doc_id": r["run"]["id"], "file_path": str(run_path.resolve())})
    for m in r.get("matches", []):
        p = out / f"{m['id']}.json"
        p.write_text(json.dumps(m))
        writes.append({"op": "set", "collection": "matches", "doc_id": m["id"], "file_path": str(p.resolve())})
    (out / "writes.json").write_text(json.dumps(writes, indent=1))
    print(f"export: {len(writes)} writes in work/out/writes.json (batches of 50 at most)")


if __name__ == "__main__":
    {"config": config, "export": export}[sys.argv[1]]()
