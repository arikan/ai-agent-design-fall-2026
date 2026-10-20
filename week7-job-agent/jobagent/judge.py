"""Score a prepared batch with a model, on this computer.

  uv run jobagent judge [--model <id>]     work/batch.json -> work/judgments.json

This is the one step that needs a model. In the cloud, the Claude session does it by reading
work/batch.json itself. Here, the same text goes to whichever model `model.py` picks (default:
Claude Code's command line with your login), a few posts at a time, and the replies are
collected into work/judgments.json in the batch's answer format. `engine.py finish` then checks
every score the same way it checks the cloud's.
"""

import json
import sys
from pathlib import Path

from . import model as llm

WORK = Path(__file__).resolve().parents[1] / "work"
PER_CALL = 4     # posts per model call: small enough for a local model, few enough calls for an API


def rubric_text(search):
    # The rubric plus the user's own input for that dimension (target roles, industries, keywords, pay),
    # as the cloud session reads them from batch.json. Without the inputs the model can't judge fit.
    return "\n".join(f"- {d['name']} (key `{d['key']}`): {d['rubric']}" + (f" {d['inputs']}" if d.get("inputs") else "")
                      for d in search["dimensions"])


def judge(batch, model=None, log=print):
    searches = {s["id"]: s for s in batch["searches"]}
    system = (batch["matcher_instructions"]
              + "\n\nAnswer with JSON only, no prose: a list with one object per post, in the shape given. "
                "Every dimension key must appear. Evidence must be copied exactly from the post's text, or empty when the score is \"unknown\".")
    shape = json.dumps(batch["answer_format"]["shape"], indent=1)
    answers, usage = [], {"model": None, "input_tokens": 0, "output_tokens": 0}
    items = batch["items"]
    for i in range(0, len(items), PER_CALL):
        chunk = items[i:i + PER_CALL]
        parts = []
        for it in chunk:
            s = searches[it["search_id"]]
            parts.append(f"## Post\nsearch_id: {it['search_id']}\nposting_id: {it['posting_id']}\n"
                         f"Title: {it['title']}\nCompany: {it['company']}\nLocation: {it['location']}\n"
                         f"Pay: {it.get('pay_min')} to {it.get('pay_max')}\n\n{it['text']}\n")
        by_search = {sid: searches[sid] for sid in {it["search_id"] for it in chunk}}
        profile = "\n\n".join(f"# Search `{sid}`\nDimensions:\n{rubric_text(s)}\n\nCV:\n{s.get('cv_text') or '(none)'}"
                              for sid, s in by_search.items())
        user = f"{profile}\n\n# Posts to score\n\n" + "\n".join(parts) + f"\n\n# Answer shape\n{shape}"
        log(f"judge: posts {i + 1} to {i + len(chunk)} of {len(items)}, {llm.chosen(model)}")
        text, u = llm.complete(system, user, model)
        usage["model"] = u.get("model") or usage["model"]
        for k in ("input_tokens", "output_tokens"):
            usage[k] += u.get(k) or 0
        try:
            got = llm.json_block(text)
        except (ValueError, json.JSONDecodeError):
            log("judge: the reply was not JSON; these posts will count as not judged")
            continue
        if isinstance(got, dict) and "scores" in got:
            got = [got]
        for a in got if isinstance(got, list) else []:
            if isinstance(a, dict) and "posting_id" in a and isinstance(a.get("scores"), dict):
                a.setdefault("search_id", chunk[0]["search_id"])
                for v in a["scores"].values():      # "4" -> 4; the check wants numbers or "unknown"
                    if isinstance(v, dict) and isinstance(v.get("score"), str) and v["score"].strip().isdigit():
                        v["score"] = int(v["score"].strip())
                answers.append(a)
    return answers, usage


def main(argv):
    m = argv[argv.index("--model") + 1] if "--model" in argv and len(argv) > argv.index("--model") + 1 else None
    batch = json.loads((WORK / "batch.json").read_text())
    answers, usage = judge(batch, m)
    (WORK / "judgments.json").write_text(json.dumps(answers, indent=1))
    (WORK / "judge_usage.json").write_text(json.dumps(usage))
    print(f"judge: {len(answers)} of {len(batch['items'])} posts scored by {usage['model'] or llm.chosen(m)}. Wrote work/judgments.json")


if __name__ == "__main__":
    main(sys.argv[1:])
