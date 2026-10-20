"""Bridge between the artifact database and the engine's files.

The engine cannot reach the database; the Claude session can. The session saves
database reads as JSON files under work/db/ (ArtifactData with out_dir), then:

  uv run jobagent db config   -> work/config.json from work/db/
  uv run jobagent db export   -> work/out/*.json plus work/out/writes.json, a ready batch
                              for the session to write back with ArtifactData
  uv run jobagent db progress <stage>
                          -> work/out/progress.json, the live status the page shows while a
                              run works (stages: fetching, filtering, judging, saving, done, stopped)
  uv run jobagent db config [manual]
                          -> the run is one the user started by hand (counted against its cap)
  uv run jobagent db seed     -> first local run: work/db gets the starting agent and search from defaults/
  uv run jobagent db apply    -> write work/out/writes.json (and the postings index) into work/db, the local database
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]     # the project folder: work/, defaults/, caps.json
WORK = HERE / "work"


def body(path):
    d = json.loads(path.read_text())
    return d.get("data", d)


def config(trigger="scheduled"):
    db = WORK / "db"
    searches = []
    for p in sorted((db / "searches").glob("*.json")):
        s = body(p)
        s["id"] = p.stem
        searches.append(s)
    # Runs the user started by hand in the last 24 hours. A rolling day, not a calendar day,
    # so it means the same thing in every time zone. The scheduled morning run is never counted.
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    manual = sorted(body(p).get("started", "") for p in (db / "runs").glob("*.json")
                    if body(p).get("trigger") == "manual" and body(p).get("status") == "ok") if (db / "runs").exists() else []
    recent = [t for t in manual if t >= since]
    # Postings already matched for a search are not judged again: only new ones cost a judgment,
    # and every database write stays a create.
    seen = {}
    for p in (db / "matches").glob("*.json") if (db / "matches").exists() else []:
        m = body(p)
        seen.setdefault(m["search_id"], []).append(m["posting_id"])
    # Rescore requests (collection `rescore`, made from the page): score these postings again this run,
    # whatever their rank, and replace their match. The user's verdict stays in `judgments`.
    rescore = {}
    for p in sorted((db / "rescore").glob("*.json")) if (db / "rescore").exists() else []:
        q = body(p)
        rescore.setdefault(q["search_id"], []).append(q["posting_id"])
        seen[q["search_id"]] = [x for x in seen.get(q["search_id"], []) if x != q["posting_id"]]
    cfg = {"trigger": trigger, "rescore": rescore, "manual_runs_24h": len(recent), "manual_runs_since": recent, "agent": body(db / "agent" / "current.json"),
           "searches": searches, "seen": seen}
    (WORK / "config.json").write_text(json.dumps(cfg, indent=2))
    print(f"config: {len(searches)} search(es), agent v{cfg['agent']['version']}, {len(recent)} run(s) by hand in the last 24 hours")


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
        w = {"op": "set", "collection": "matches", "doc_id": m["id"], "file_path": str(p.resolve())}
        if m.get("rescored"):
            w["if_version"] = 1      # replaces the earlier match, which runs write once and never update
            writes.append({"op": "delete", "collection": "rescore", "doc_id": m["id"], "if_version": 1})
        writes.append(w)
    snap = snapshot(r["run"], out)
    writes.extend(snap)
    (out / "writes.json").write_text(json.dumps(writes, indent=1))
    print(f"export: {len(writes)} writes in work/out/writes.json (batches of 50 at most), {len(snap)} of them the day's postings")


CHUNK_BYTES = 180_000   # a document may hold 256 KiB; keep chunks well under it


def snapshot(run, out):
    """The day's collected postings, in chunks the page can load, so the Search tab can rank them
    without a run. Chunk ids carry the run id, so every write is a create; the page deletes
    yesterday's. The index goes to work/out/postings-index.json for the session to write to
    meta/postings with its version."""
    path = WORK / "postings.json"
    if not path.exists():
        return []
    items = json.loads(path.read_text())
    chunks, cur, size = [], [], 0
    for it in items:
        n = len(json.dumps(it))
        if cur and size + n > CHUNK_BYTES:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(it)
        size += n
    if cur:
        chunks.append(cur)
    writes, ids = [], []
    for i, chunk in enumerate(chunks):
        doc_id = f"{run['id']}-{i:02d}"
        p = out / f"postings-{i:02d}.json"
        p.write_text(json.dumps({"run_id": run["id"], "n": i, "items": chunk}))
        writes.append({"op": "set", "collection": "postings", "doc_id": doc_id, "file_path": str(p.resolve())})
        ids.append(doc_id)
    (out / "postings-index.json").write_text(json.dumps({
        "run_id": run["id"], "collected_at": run["started"], "count": len(items), "chunks": ids,
        "sources": [{"id": s["source"], "status": s["status"], "fetched": s.get("fetched"), "kept": s.get("kept")}
                    for s in run.get("sources", []) if s.get("status") != "manual"]}, indent=1))
    return writes


STAGES = [("fetching", "Collect job posts"), ("filtering", "Filter and rank"),
          ("judging", "Score the best candidates"), ("saving", "Save matches")]


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


LOCAL = False     # set by run.py local: no session page to link, whatever the environment says


def session_url():
    """This Claude Code session's page, where the run can be watched or stopped (cse_X is claude.ai/code/session_X)."""
    import os
    if LOCAL:
        return None
    sid = os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID", "")
    return "https://claude.ai/code/" + sid.replace("cse_", "session_", 1) if sid else None


def progress(stage):
    """Summarize what the run has done so far, from the files the engine already wrote."""
    out = WORK / "out"
    out.mkdir(parents=True, exist_ok=True)
    started = WORK / "progress_started"
    if not started.exists():
        started.write_text(datetime.now(timezone.utc).isoformat())
    cfg = read(WORK / "config.json", {})
    health = {h["source"]: h for h in read(WORK / "fetch_health.json", [])}
    sources = []
    for src in (cfg.get("agent") or {}).get("sources", []):
        if not src.get("enabled") or src["adapter"] == "manual":
            continue
        h = health.get(src["id"])
        sources.append({"id": src["id"], "name": (src.get("config") or {}).get("company_name") or src["id"],
                        "status": h["status"] if h else ("waiting" if stage == "fetching" else "skipped"),
                        "fetched": (h or {}).get("fetched"), "kept": (h or {}).get("kept"),
                        "error": ((h or {}).get("error") or "")[:160] or None})
    counts = {"collected": sum(s["kept"] or 0 for s in sources)} if health else {}
    state = read(WORK / "state.json")
    if state:
        for t in state.get("trace", []):
            if t["step"] == "normalize":
                counts["unique"] = t["postings"]
            if t["step"] == "filter":
                counts["already_seen"] = counts.get("already_seen", 0) + t["already_matched"]
                counts["dropped"] = counts.get("dropped", 0) + t["dropped"]
                counts["to_score"] = counts.get("to_score", 0) + t["sent_to_judge"]
    results = read(WORK / "results.json")
    if results and stage in ("saving", "done", "stopped"):
        counts["matches"] = len(results.get("matches", []))
        counts["rejected"] = results["run"].get("rejected", 0)
    keys = [k for k, _ in STAGES]
    at = keys.index(stage) if stage in keys else len(keys)
    doc = {"stage": stage, "started_at": started.read_text(), "updated_at": datetime.now(timezone.utc).isoformat(),
           "run_id": (results or {}).get("run", {}).get("id") or (read(WORK / "batch.json") or {}).get("run_id"),
           "steps": [{"key": k, "label": label, "status": "done" if i < at else "active" if i == at else "pending"}
                     for i, (k, label) in enumerate(STAGES)],
           "sources": sources, "counts": counts, "session_url": session_url()}
    if stage == "stopped" and results:
        doc["note"] = results["run"].get("cap_hit")
    (out / "progress.json").write_text(json.dumps(doc, indent=1))
    if (WORK / "db").exists():          # the local database, when runs happen on this computer
        from . import localdb
        localdb.write("meta/progress", doc)
    print(f"progress: {stage}, {len(sources)} source(s), {counts}")


def seed():
    """A local database with the starting agent and search from defaults/, when there is none yet."""
    from . import localdb
    now = datetime.now(timezone.utc).isoformat()
    made = []
    if not localdb.read("agent/current"):
        agent = {**json.loads((HERE / "defaults" / "agent.json").read_text()), "updated": now}
        localdb.write("agent/current", agent)
        localdb.write(f"agent/current/versions/v{agent['version']}", {"version": agent["version"], "note": "Starting settings", "updated": now})
        made.append("agent")
    if not localdb.list_docs("searches"):
        s = json.loads((HERE / "defaults" / "search.json").read_text())
        localdb.write("searches/my-first-search", {**s, "updated": now})
        made.append("search my-first-search")
    if not localdb.read("meta/agent"):
        localdb.write("meta/agent", {"trigger_id": "local", "name": "uv run jobagent run", "connected_at": now, "local": True})
        localdb.write("meta/setup_check", {"status": "ok", "finished_at": now, "local": True})
        made.append("local runner")
    print("seed: " + (", ".join(made) if made else "nothing to do, work/db already has an agent and a search"))


def apply():
    """Write a finished run into the local database: what the cloud session does with ArtifactData."""
    from . import localdb
    out = WORK / "out"
    writes = read(out / "writes.json", [])
    n = 0
    for w in writes:
        if w["op"] == "delete":
            localdb.delete(f"{w['collection']}/{w['doc_id']}")
        else:
            data = json.loads(Path(w["file_path"]).read_text()) if "file_path" in w else w.get("data", {})
            if w["op"] == "update":
                localdb.update(f"{w['collection']}/{w['doc_id']}", data)
            else:
                localdb.write(f"{w['collection']}/{w['doc_id']}", data)
        n += 1
    idx = read(out / "postings-index.json")
    if idx:
        old = localdb.read("meta/postings")
        for cid in (old or {}).get("data", {}).get("chunks", []):      # yesterday's chunks
            if cid not in idx["chunks"]:
                localdb.delete("postings/" + cid)
        localdb.write("meta/postings", idx)
    prog = read(out / "progress.json")
    if prog:
        localdb.write("meta/progress", prog)
    if writes:
        (out / "writes.json").rename(out / "writes.applied.json")
    print(f"apply: {n} write(s) into work/db")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "seed":
        seed()
    elif cmd == "apply":
        apply()
    elif cmd == "progress" and len(sys.argv) == 3:
        progress(sys.argv[2])
    elif cmd == "config":
        config("manual" if "manual" in sys.argv[2:] else "scheduled")
    elif cmd == "export":
        export()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
