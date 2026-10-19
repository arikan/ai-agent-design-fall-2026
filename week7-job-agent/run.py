"""One command per half of a run, so the cloud session spends its turns only where Claude is needed.

  uv run run.py prepare   work/db/ -> config, fetch, filter, rank -> work/batch.json, progress "judging"
                          (or "stopped" when today's run already happened; nothing is fetched then)
  uv run run.py finish    work/judgments.json -> check, rank -> work/out/writes.json, progress "done"

Each prints one line per stage with how long it took.
"""

import json
import sys
import time

import dbio
import engine
import sources

CAPS = json.loads((engine.HERE / "caps.json").read_text())


def timed(label, fn, *args):
    t = time.time()
    fn(*args)
    print(f"[{label}: {time.time() - t:.1f}s]")


def prepare():
    timed("config", dbio.config)
    cfg_path = dbio.WORK / "config.json"
    cfg = json.loads(cfg_path.read_text())
    if cfg.get("runs_today", 0) >= CAPS["max_runs_per_day"]:
        timed("prepare", engine.prepare, cfg)          # records the stop; nothing is fetched
        dbio.export()
        dbio.progress("stopped")
        return
    timed("fetch", sources.fetch, str(cfg_path))
    timed("prepare", engine.prepare, cfg)
    dbio.progress("judging")


def finish():
    cfg = json.loads((dbio.WORK / "config.json").read_text())
    timed("finish", engine.finish, cfg)
    dbio.export()
    dbio.progress("done")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("prepare", "finish"):
        sys.exit(__doc__)
    {"prepare": prepare, "finish": finish}[cmd]()
