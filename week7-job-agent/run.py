"""One command per half of a run, so the cloud session spends its turns only where Claude is needed.

  uv run run.py prepare [manual]   work/db/ -> config, fetch, filter, rank -> work/batch.json, progress "judging"
                                   (`manual` marks a run the user started by hand; those are capped)
  uv run run.py finish [--model <id>]
                                   work/judgments.json -> check, rank -> work/out/writes.json, progress "done"
                                   (`--model` records which model did the scoring, on the run and its matches)

Each prints one line per stage with how long it took, and the run record keeps those times.
"""

import json
import sys
import time
from datetime import datetime, timezone

import dbio
import engine
import sources
import usage

CAPS = json.loads((engine.HERE / "caps.json").read_text())
TIMINGS = dbio.WORK / "timings.json"


def timed(times, label, fn, *args):
    t = time.time()
    fn(*args)
    times[label] = round(time.time() - t, 1)
    print(f"[{label}: {times[label]}s]")
    TIMINGS.write_text(json.dumps(times))


def attach(times, model=None):
    """Put the stage times, and the scoring model, into the results the engine wrote."""
    r = json.loads((dbio.WORK / "results.json").read_text())
    r["run"]["timings"] = times
    if dbio.session_url():
        r["run"]["session_url"] = dbio.session_url()
    u = usage.session_usage()
    if u:
        r["run"]["usage"] = u
        model = model or u["model"]      # the transcript knows which model actually answered
    if model:
        r["run"]["model"] = model
        for m in r.get("matches", []):
            m["model"] = model
    (dbio.WORK / "results.json").write_text(json.dumps(r, indent=2))


def prepare(trigger):
    times = {}
    timed(times, "config", dbio.config, trigger)
    cfg_path = dbio.WORK / "config.json"
    cfg = json.loads(cfg_path.read_text())
    if trigger == "manual" and cfg.get("manual_runs_24h", 0) >= CAPS["max_manual_runs_per_day"]:
        timed(times, "prepare", engine.prepare, cfg)          # records the stop; nothing is fetched
        attach(times)
        dbio.export()
        dbio.progress("stopped")
        return
    timed(times, "fetch", sources.fetch, str(cfg_path))
    timed(times, "prepare", engine.prepare, cfg)
    times["prepared_at"] = datetime.now(timezone.utc).isoformat()
    TIMINGS.write_text(json.dumps(times))
    dbio.progress("judging")


def finish(model=None):
    cfg = json.loads((dbio.WORK / "config.json").read_text())
    times = json.loads(TIMINGS.read_text()) if TIMINGS.exists() else {}
    if "prepared_at" in times:      # the gap between the two halves is Claude's judging
        times["judge"] = round(time.time() - datetime.fromisoformat(times.pop("prepared_at")).timestamp(), 1)
    timed(times, "finish", engine.finish, cfg)
    attach(times, model)
    dbio.export()
    dbio.progress("done")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "prepare":
        prepare("manual" if "manual" in sys.argv[2:] else "scheduled")
    elif cmd == "finish":
        args = sys.argv[2:]
        finish(args[args.index("--model") + 1] if "--model" in args and len(args) > args.index("--model") + 1 else None)
    else:
        sys.exit(__doc__)
