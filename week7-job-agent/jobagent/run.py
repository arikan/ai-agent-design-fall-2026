"""One command per half of a run, so the cloud session spends its turns only where Claude is needed.

  uv run jobagent prepare [manual]   work/db/ -> config, fetch, filter, rank -> work/batch.json, progress "judging"
                                   (`manual` marks a run the user started by hand; those are capped)
  uv run jobagent finish [--model <id>]
                                   work/judgments.json -> check, rank -> work/out/writes.json, progress "done"
                                   (`--model` records which model did the scoring, on the run and its matches)
  uv run jobagent run [manual] [--model <id>]
                                   the whole run on this computer: prepare, score with judge.py, finish, and
                                   write the results into work/db, the local database serve.py shows
  uv run jobagent suggest [--model <id>]
                                   suggest Profile changes from the verdicts in work/db, on this computer

Each prints one line per stage with how long it took, and the run record keeps those times.
"""

import json
import sys
import time
from datetime import datetime, timezone

from . import dbio
from . import engine
from . import sources
from . import usage

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
    local = dbio.read(dbio.WORK / "judge_usage.json")
    if local and local.get("model"):        # scored on this computer by judge.py
        u = {"model": local["model"], "input": local.get("input_tokens") or 0, "output": local.get("output_tokens") or 0,
             "cache_write": 0, "cache_read": 0, "source": "judge.py"}
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
        return False
    timed(times, "fetch", sources.fetch, str(cfg_path))
    timed(times, "prepare", engine.prepare, cfg)
    times["prepared_at"] = datetime.now(timezone.utc).isoformat()
    TIMINGS.write_text(json.dumps(times))
    dbio.progress("judging")
    return True


def finish(model=None):
    cfg = json.loads((dbio.WORK / "config.json").read_text())
    times = json.loads(TIMINGS.read_text()) if TIMINGS.exists() else {}
    if "prepared_at" in times:      # the gap between the two halves is Claude's judging
        times["judge"] = round(time.time() - datetime.fromisoformat(times.pop("prepared_at")).timestamp(), 1)
    timed(times, "finish", engine.finish, cfg)
    attach(times, model)
    dbio.export()
    dbio.progress("done")


def local(trigger, model=None):
    """Everything the cloud run does, here: the database is work/db and the model is judge.py's."""
    from . import judge
    from . import model as llm
    dbio.LOCAL = True
    dbio.seed()
    for stale in ("judgments.json", "judge_usage.json"):
        (dbio.WORK / stale).unlink(missing_ok=True)
    if not prepare(trigger):        # stopped on the course cap; the run record says so
        dbio.apply()
        return
    batch = json.loads((dbio.WORK / "batch.json").read_text())
    if batch["items"]:
        answers, u = judge.judge(batch, model)
        (dbio.WORK / "judgments.json").write_text(json.dumps(answers, indent=1))
        (dbio.WORK / "judge_usage.json").write_text(json.dumps(u))
    else:
        (dbio.WORK / "judgments.json").write_text("[]")
        print("judge: nothing to score this run")
    finish(llm.chosen(model) if not (dbio.WORK / "judge_usage.json").exists() else None)
    r = json.loads((dbio.WORK / "results.json").read_text())
    for t in r["run"].get("trace", []):
        if t.get("step") == "judge":
            for rej in t.get("rejections", [])[:8]:
                print(f"rejected {rej['posting']}: {'; '.join(rej['errors'])[:160]}")
    dbio.apply()


def suggest_local(model=None):
    from . import suggest
    dbio.LOCAL = True
    from . import model as llm
    suggest.prepare()
    if not (dbio.WORK / "suggest.json").exists():
        return
    task = json.loads((dbio.WORK / "suggest.json").read_text())
    if not task["searches"]:
        return
    system = "You improve a job agent's profile from its user's verdicts. Answer with JSON only, in the answer shape."
    user = json.dumps({k: task[k] for k in ("instructions", "matcher_instructions", "searches")}, indent=1) + \
        "\n\nAnswer shape:\n" + json.dumps(task["answer_format"]["shape"], indent=1)
    text, u = llm.complete(system, user, model)
    (dbio.WORK / "suggestions.json").write_text(json.dumps(llm.json_block(text)))
    suggest.finish(u.get("model") or llm.chosen(model))
    from . import localdb
    doc = json.loads((dbio.WORK / "out" / "suggestion.json").read_text())
    localdb.write("suggestions/" + doc["id"], doc)
    print(f"suggest: written to work/db as suggestions/{doc['id']}")


def flag(args, name):
    return args[args.index(name) + 1] if name in args and len(args) > args.index(name) + 1 else None


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "local":
        local("manual" if "manual" in sys.argv[2:] else "scheduled", flag(sys.argv[2:], "--model"))
    elif cmd == "suggest":
        suggest_local(flag(sys.argv[2:], "--model"))
    elif cmd == "prepare":
        prepare("manual" if "manual" in sys.argv[2:] else "scheduled")
    elif cmd == "finish":
        args = sys.argv[2:]
        finish(args[args.index("--model") + 1] if "--model" in args and len(args) > args.index("--model") + 1 else None)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
