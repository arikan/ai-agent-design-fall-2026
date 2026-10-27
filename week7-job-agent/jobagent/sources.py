"""Run job sources through their adapters.

  uv run jobagent sources fetch   work/config.json   fetch every enabled source -> work/fetched/, work/fetch_health.json
  uv run jobagent sources try     source.json [out]  run one source live and show a sample (for tests and repairs)
  uv run jobagent sources test                       run every adapter against its saved responses, offline
  uv run jobagent sources domains work/config.json   domains to allow in the cloud environment's network setting
"""

import json
import re
import sys
from pathlib import Path

from .adapters import NON_FETCHING, adapter_class, domains_for
from .adapters.http import Http

HERE = Path(__file__).resolve().parents[1]     # the project folder: work/, defaults/, caps.json
WORK = HERE / "work"
CAPS = json.loads((HERE / "caps.json").read_text())


def safe(source_id):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", source_id)


def run_source(source, fixtures=None, roles=None):
    if (source.get("config") or {}).get("url_template"):
        return run_template(source, fixtures, roles)
    cls = adapter_class(source)
    http = Http(domains_for(source), fixtures=fixtures)
    cap = min(int(source.get("cap", CAPS["max_postings_per_source"])), CAPS["max_postings_per_source"])
    return cls(source["id"], source.get("config", {}), http).run(cap)


MAX_TEMPLATE_ROLES = 8


def expand(template, role):
    """An address with {role} in it, for one target role: "Head of Product" goes in as Head+of+Product."""
    from urllib.parse import quote_plus
    return template.replace("{role}", quote_plus(role))


def run_template(source, fixtures=None, roles=None):
    """A search page or API whose address takes a role (an aggregator such as Built In): one request per target
    role from the profile, so the source narrows itself as the profile changes. Posts found by several roles
    are kept once."""
    cfg = source["config"]
    roles = [r for r in (roles or profile_roles()) if r.strip()][:MAX_TEMPLATE_ROLES]
    if not roles:
        return [], {"source": source["id"], "status": "failed", "error": "this source searches by your target roles, and the profile has none", "fetched": 0, "kept": 0}
    seen, postings = set(), []
    health = {"source": source["id"], "status": "ok", "fetched": 0, "kept": 0, "rejected": 0, "capped": 0, "requests": [], "by_role": {}}
    errors = []
    for role in roles:
        one = {**source, "config": {**{k: v for k, v in cfg.items() if k != "url_template"}, "url": expand(cfg["url_template"], role)}}
        try:
            ps, h = run_source(one, fixtures)
        except Exception as e:
            ps, h = [], {"status": "failed", "error": f"{type(e).__name__}: {e}"[:200]}
        health["by_role"][role] = h.get("kept", 0)
        health["fetched"] += h.get("fetched") or 0
        health["rejected"] += h.get("rejected") or 0
        health["requests"] += h.get("requests", [])
        if h.get("status") == "failed":
            errors.append(f"{role}: {h.get('error')}")
        for p in ps:
            key = p.get("url") or (p.get("company"), p.get("title"), p.get("location"))
            if key not in seen:
                seen.add(key)
                postings.append(p)
    cap = min(int(source.get("cap", CAPS["max_postings_per_source"])), CAPS["max_postings_per_source"])
    health["capped"] = max(0, len(postings) - cap)
    postings = postings[:cap]
    health["kept"] = len(postings)
    if errors and not postings:
        health.update(status="failed", error="; ".join(errors)[:300])
    elif not postings:
        health["status"] = "empty"
    return postings, health


def profile_roles():
    """Target roles of the active searches, from the run's config or the local database."""
    roles = []
    cfg = WORK / "config.json"
    searches = json.loads(cfg.read_text()).get("searches", []) if cfg.exists() else []
    if not searches and (WORK / "db" / "searches").exists():
        for p in sorted((WORK / "db" / "searches").glob("*.json")):
            d = json.loads(p.read_text())
            searches.append(d.get("data", d))
    for s in searches:
        if s.get("active", True):
            roles += [r for r in s.get("target_roles", []) if r not in roles]
    return roles


def fetch(config_path):
    cfg = json.loads(Path(config_path).read_text())
    out = WORK / "fetched"
    out.mkdir(parents=True, exist_ok=True)
    health = []
    for src in cfg["agent"]["sources"]:
        if not src.get("enabled") or src["adapter"] in NON_FETCHING:
            continue
        try:
            postings, h = run_source(src)
        except Exception as e:      # a broken custom adapter or bad config
            postings, h = [], {"source": src["id"], "status": "failed", "error": f"{type(e).__name__}: {e}"[:300]}
        (out / f"{safe(src['id'])}.jsonl").write_text("".join(json.dumps(p) + "\n" for p in postings))
        health.append(h)
        print(f"{src['id']:<28} {h['status']:<7} kept {h.get('kept', 0):>3}  {h.get('error') or ''}")
    (WORK / "fetch_health.json").write_text(json.dumps(health, indent=1))


def try_source(path, out=None):
    """Run one source. With `out`, also write the result for the console: health,
    the requests made, and up to five sample postings."""
    src = json.loads(Path(path).read_text())
    try:
        postings, h = run_source(src)
    except Exception as e:      # broken custom adapter or bad settings
        postings, h = [], {"source": src.get("id"), "status": "failed", "error": f"{type(e).__name__}: {e}"[:300]}
    short = lambda v, n: v[:n] + "…" if isinstance(v, str) and len(v) > n else v
    result = {"source_id": src.get("id"), "health": {k: v for k, v in h.items() if k != "requests"},
              "requests": h.get("requests", [])[:10],
              "sample": [{k: short(p.get(k), 400) for k in ("title", "company", "location", "remote", "pay_min",
                                                             "pay_max", "url", "text")} for p in postings[:5]]}
    if out:
        Path(out).write_text(json.dumps(result, indent=1))
    print(json.dumps({"health": result["health"], "sample": [{k: short(v, 120) for k, v in p.items()} for p in result["sample"][:3]]}, indent=1))


def test():
    failures = 0
    for fx_path in sorted((Path(__file__).resolve().parent / "adapters" / "fixtures").glob("*.json")):
        fx = json.loads(fx_path.read_text())
        postings, h = run_source(fx["source"], fixtures=fx["responses"])
        exp = fx["expect"]
        problems = []
        if h["status"] != exp.get("status", "ok"):
            problems.append(f"status {h['status']} ({h.get('error')})")
        if "kept" in exp and h["kept"] != exp["kept"]:
            problems.append(f"kept {h['kept']}, expected {exp['kept']}")
        for field, want in (exp.get("first") or {}).items():
            got = postings[0].get(field) if postings else None
            if got != want:
                problems.append(f"first.{field} = {got!r}, expected {want!r}")
        failures += bool(problems)
        print(f"{fx_path.stem:<14} {'ok' if not problems else 'FAIL'}  " + "; ".join(problems))
    sys.exit(1 if failures else 0)


def domains(config_path):
    cfg = json.loads(Path(config_path).read_text())
    ds = sorted({d for s in cfg["agent"]["sources"] if s.get("enabled") for d in domains_for(s)})
    print("\n".join(ds))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "test":
        test()
    elif cmd == "try" and len(sys.argv) in (3, 4):
        try_source(*sys.argv[2:])
    elif cmd in ("fetch", "domains") and len(sys.argv) == 3:
        {"fetch": fetch, "domains": domains}[cmd](sys.argv[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
