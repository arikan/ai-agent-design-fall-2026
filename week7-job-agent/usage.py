"""Token usage of the Claude session running this run, read from its own transcript.

Claude Code writes every model call to ~/.claude/projects/<project>/<session>.jsonl with its
token counts. The newest transcript is the running session's. One call can appear on several
lines (one per content block), so calls are counted once by message id.

  uv run usage.py      print this session's usage so far
"""

import json
from pathlib import Path


def session_usage():
    files = sorted(Path.home().glob(".claude/projects/*/*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    calls, models = {}, {}
    for line in files[-1].read_text(errors="ignore").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        m = d.get("message") or {}
        if d.get("type") != "assistant" or not m.get("usage") or not m.get("id"):
            continue
        calls[m["id"]] = m["usage"]
        if m.get("model"):
            models[m["model"]] = models.get(m["model"], 0) + 1
    if not calls:
        return None
    total = lambda k: sum(u.get(k) or 0 for u in calls.values())
    write_1h = sum((u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0 for u in calls.values())
    return {"calls": len(calls),
            "input": total("input_tokens"), "cache_write": total("cache_creation_input_tokens"), "cache_write_1h": write_1h,
            "cache_read": total("cache_read_input_tokens"), "output": total("output_tokens"),
            "model": max(models, key=models.get) if models else None,
            "note": "the session's model calls up to the end of scoring; the final writes back to the page are not included"}


if __name__ == "__main__":
    print(json.dumps(session_usage(), indent=1))
