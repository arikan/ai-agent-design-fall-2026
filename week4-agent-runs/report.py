#!/usr/bin/env python3
"""Compare agent session logs (.jsonl) run by run. Reads Claude Code logs (~/.claude/projects/...) and pi logs (~/.pi/agent/sessions/...); the format is detected per file.

Usage:
  python3 report.py                                              -> pick one run per setup (Claude Code, pi cloud, pi local)
  python3 report.py run_a.jsonl run_b.jsonl [more.jsonl ...]     -> report.md, with traces
      [--label A --label B ...]              column names; by default harness+model read from each log, e.g. cc+fable-5, pi+gemma4
      [--price LABEL=IN,OUT[,CACHEWRITE,CACHEREAD]]  override or add prices, USD per million tokens. Claude models are priced from a built-in table.
      [--no-timeline]                        leave the per-run traces out
      [--md out.md]                          report file (default report.md; - for stdout only)
      [--full]                               the detailed report: every counter, every step, the recorded reasoning

What it reads from each log: the model name, wall-clock span, number of model calls, tokens in and out
(with cache reads and writes when the log has them), thinking blocks, tool calls by tool, files touched,
tool errors, and the final assistant text. Unknown line shapes are skipped, not fatal.
"""

import argparse
import fnmatch
import glob
import json
import re
import statistics
import sys
import os
from collections import Counter, OrderedDict
from datetime import datetime, timezone


# USD per million tokens: (input, output, cache write, cache read). Anthropic list prices, platform.claude.com, September 2026.
# Matched by substring of the model name, first match wins, so the more specific names come first.
PRICES = [
    ("fable-5-1", (10.0, 50.0, 12.50, 0.25)),
    ("mythos-5-1", (10.0, 50.0, 12.50, 0.25)),
    ("fable-5", (10.0, 50.0, 12.50, 1.00)),
    ("opus-5-5", (4.0, 20.0, 5.00, 0.20)),  # Anthropic's ID
    ("opus-5.5", (4.0, 20.0, 5.00, 0.20)),  # the same model as named by OpenRouter and GitHub Copilot
    ("opus-5", (5.0, 25.0, 6.25, 0.50)),
    ("sonnet-5", (2.0, 10.0, 2.50, 0.20)),
    ("haiku-4-5", (1.0, 5.0, 1.25, 0.10)),
]


def price_for(model_name):
    m = (model_name or "").lower()
    for key, p in PRICES:
        if key in m:
            return p
    return None


def is_local(models):
    names = json.dumps(models).lower()
    return "ollama" in names or any(
        ":" in m for m in models
    )  # Ollama tags look like gemma4:26b


def cost_breakdown(r, p):
    pin, pout, pcw, pcr = p
    parts = OrderedDict()
    parts["output"] = r["output_tokens"] * pout / 1e6
    parts["cache write"] = r["cache_write"] * pcw / 1e6
    parts["cache read"] = r["cache_read"] * pcr / 1e6
    parts["input"] = r["input_tokens"] * pin / 1e6
    return sum(parts.values()), parts


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def blocks_of(msg):
    """Normalize message.content into a list of blocks."""
    if msg is None:
        return []
    c = msg.get("content") if isinstance(msg, dict) else None
    if c is None:
        return []
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    return [b for b in c if isinstance(b, dict)]


def short(v, n=70):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def tool_arg(name, inp):
    """One readable argument per tool, for the timeline."""
    if not isinstance(inp, dict):
        return short(inp)
    for k in (
        "file_path",
        "path",
        "command",
        "pattern",
        "query",
        "url",
        "prompt",
        "description",
    ):
        if k in inp:
            return short(inp[k])
    return short(inp)


def load(path):
    events = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                sys.stderr.write(f"{path}:{i + 1}: skipped unparsable line\n")
    return events


def detect(ev):
    for e in ev:
        if e.get("type") == "session" or (
            e.get("type") == "message"
            and isinstance(e.get("message"), dict)
            and e["message"].get("role") in ("assistant", "user", "toolResult")
        ):
            return "pi"
        if e.get("type") in ("user", "assistant") and isinstance(
            e.get("message"), dict
        ):
            return "claude-code"
    return "claude-code"


def find_key(obj, key):
    """Last value of `key` found anywhere in a nested dict/list."""
    found = None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and v is not None:
                found = v
            else:
                sub = find_key(v, key)
                if sub is not None:
                    found = sub
    elif isinstance(obj, list):
        for v in obj:
            sub = find_key(v, key)
            if sub is not None:
                found = sub
    return found


def harness_tally(ev):
    tally = None
    for e in ev:
        v = find_key(e, "totalCostUSD")
        if isinstance(v, (int, float)):
            tally = float(v)
    return tally


def analyze(path):
    ev = load(path)
    r = analyze_pi(path, ev) if detect(ev) == "pi" else analyze_cc(path, ev)
    r["cwd"] = next((e["cwd"] for e in ev if isinstance(e.get("cwd"), str)), None)
    return r


# cat > file <<'EOF' … EOF, the usual way to write a file from a shell
HEREDOC = re.compile(r"cat\s*>\s*['\"]?([^\s'\"<]+)['\"]?\s*<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\2\s*$", re.S | re.M)


def record_write(writes, name, inp):
    """Note a file the model wrote or edited: (path, full content for a whole-file write, else None)."""
    if name.lower() == "bash" and isinstance(inp.get("command"), str):
        for path, _, content in HEREDOC.findall(inp["command"]):
            writes.append((path, content + "\n"))
        return
    if name.lower() not in ("write", "edit", "multiedit"):
        return
    path = inp.get("file_path") or inp.get("path")
    if isinstance(path, str):
        content = inp.get("content") if name.lower() == "write" else None
        writes.append((path, content if isinstance(content, str) else None))


def g(d, *keys, default=0):
    """First present key among alternatives."""
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return default


def analyze_pi(path, ev):
    """pi coding agent session: {type:'message', timestamp, message:{role, content:[...], usage, model, provider}}."""
    r = OrderedDict()
    r["file"] = os.path.basename(path)
    r["path"] = os.path.abspath(path)
    r["harness"] = "pi"
    conv = [parse_ts(e.get("timestamp")) for e in ev if e.get("type") == "message"]
    conv = [t for t in conv if t]
    r["start"] = min(conv) if conv else None
    r["end"] = max(conv) if conv else None
    r["wall_seconds"] = (max(conv) - min(conv)).total_seconds() if conv else None
    models = Counter()
    calls = 0
    tok = Counter()
    cost = 0.0
    thinking_blocks = 0
    thinking_chars = 0
    text_chars = 0
    tools = Counter()
    files = set()
    commands = []
    errors = 0
    last_text = ""
    user_turns = 0
    timeline = []
    thinking_texts = []
    spans = []  # (request sent, reply logged, output tokens) per model call
    writes = []
    t0 = r["start"]
    for e in ev:
        if e.get("type") != "message" or not isinstance(e.get("message"), dict):
            continue
        t = parse_ts(e.get("timestamp"))
        off = (t - t0).total_seconds() if (t and t0) else None
        msg = e["message"]
        role = msg.get("role")
        if role == "assistant":
            calls += 1
            sent = msg.get("timestamp")
            if t and isinstance(sent, (int, float)):
                start = datetime.fromtimestamp(sent / 1000, tz=timezone.utc)
                spans.append((start, t, g(msg.get("usage") or {}, "output", "output_tokens")))
            m = msg.get("model") or e.get("model")
            if m:
                models[
                    (msg.get("provider") + "/" if msg.get("provider") else "") + str(m)
                ] += 1
            u = msg.get("usage") or {}
            tok["input_tokens"] += g(u, "input", "input_tokens")
            tok["output_tokens"] += g(u, "output", "output_tokens")
            tok["cache_read_input_tokens"] += g(
                u, "cacheRead", "cache_read", "cache_read_input_tokens"
            )
            tok["cache_creation_input_tokens"] += g(
                u, "cacheWrite", "cache_write", "cache_creation_input_tokens"
            )
            c = u.get("cost")
            if isinstance(c, dict):
                cost += float(g(c, "total", default=0) or 0)
            elif isinstance(c, (int, float)):
                cost += float(c)
            for b in blocks_of(msg):
                bt = b.get("type")
                if bt == "thinking":
                    thinking_blocks += 1
                    n = len(b.get("thinking") or "")
                    thinking_chars += n
                    if n:
                        thinking_texts.append((off, b.get("thinking")))
                    timeline.append((off, "model", "thinking", f"{n} chars"))
                elif bt == "text":
                    txt = b.get("text") or ""
                    text_chars += len(txt)
                    if txt.strip():
                        last_text = txt
                    timeline.append((off, "model", "text", short(txt)))
                elif bt in ("toolCall", "tool_call", "tool_use"):
                    name = b.get("name") or "?"
                    tools[name] += 1
                    inp = b.get("arguments") or b.get("input") or {}
                    if isinstance(inp, dict):
                        for k in ("path", "file_path"):
                            if isinstance(inp.get(k), str):
                                files.add(inp[k])
                        record_write(writes, name, inp)
                        if name.lower() == "bash" and isinstance(
                            inp.get("command"), str
                        ):
                            commands.append(inp["command"])
                    timeline.append(
                        (off, "model", f"tool_use {name}", tool_arg(name, inp))
                    )
            if u:
                timeline.append(
                    (
                        off,
                        "model",
                        "usage",
                        f"in {g(u, 'input', 'input_tokens')} · out {g(u, 'output', 'output_tokens')}"
                        + (
                            f" · cache read {g(u, 'cacheRead', 'cache_read')}"
                            if g(u, "cacheRead", "cache_read")
                            else ""
                        )
                        + (
                            f" · cache write {g(u, 'cacheWrite', 'cache_write')}"
                            if g(u, "cacheWrite", "cache_write")
                            else ""
                        ),
                    )
                )
        elif role == "toolResult":
            is_err = bool(msg.get("isError") or msg.get("is_error"))
            if is_err:
                errors += 1
            content = msg.get("content")
            if isinstance(content, list):
                content = " ".join(
                    (c.get("text") or "") for c in content if isinstance(c, dict)
                )
            timeline.append(
                (
                    off,
                    "tool",
                    "result" + (" ERROR" if is_err else ""),
                    short(content or ""),
                )
            )
        elif role == "user":
            user_turns += 1
            content = msg.get("content")
            if isinstance(content, list):
                content = " ".join(
                    (c.get("text") or "") for c in content if isinstance(c, dict)
                )
            if user_turns == 1:
                r["first_prompt"] = (content or "").strip()
            timeline.append((off, "person", "prompt", short(clean_prompt(content))))
    r.update(
        models=dict(models),
        model_calls=calls,
        user_turns=user_turns,
        input_tokens=tok["input_tokens"],
        output_tokens=tok["output_tokens"],
        cache_read=tok["cache_read_input_tokens"],
        cache_write=tok["cache_creation_input_tokens"],
        thinking_blocks=thinking_blocks,
        thinking_chars=thinking_chars,
        text_chars=text_chars,
        tools=dict(tools),
        tool_calls=sum(tools.values()),
        files=sorted(files),
        commands=commands,
        tool_errors=errors,
        final_text=last_text,
        timeline=timeline,
        logged_cost=cost,
        thinking_texts=thinking_texts,
        harness_tally=harness_tally(ev),
        spans=spans,
        writes=writes,
    )
    return r


def analyze_cc(path, ev):
    """Claude Code session log."""
    r = OrderedDict()
    r["file"] = os.path.basename(path)
    r["path"] = os.path.abspath(path)
    r["harness"] = "Claude Code"
    times = [parse_ts(e.get("timestamp")) for e in ev]
    times = [t for t in times if t]
    r["start"] = min(times) if times else None
    r["end"] = max(times) if times else None
    conv = [
        parse_ts(e.get("timestamp"))
        for e in ev
        if e.get("type") in ("user", "assistant")
    ]
    conv = [t for t in conv if t]
    r["start"] = min(conv) if conv else r["start"]
    r["wall_seconds"] = (max(conv) - min(conv)).total_seconds() if conv else None

    models = Counter()
    calls = 0
    tok = Counter()
    thinking_blocks = 0
    thinking_chars = 0
    text_chars = 0
    tools = Counter()
    files = set()
    commands = []
    errors = 0
    last_text = ""
    user_turns = 0
    timeline = []
    thinking_texts = []
    seen_calls = set()
    seen_usage_lines = set()
    spans = {}  # request id -> [request sent, last block logged, output tokens]
    writes = []
    last_input = None
    t0 = r["start"]

    for e in ev:
        t = parse_ts(e.get("timestamp"))
        off = (t - t0).total_seconds() if (t and t0) else None
        typ = e.get("type")
        msg = e.get("message") if isinstance(e.get("message"), dict) else None
        if typ == "assistant" and msg:
            # Claude Code writes one line per content block; lines of one model call share a request id
            # (or message id). Count the call and its usage once.
            u = msg.get("usage") or {}
            rid = (
                e.get("requestId")
                or msg.get("id")
                or json.dumps(u, sort_keys=True) + str(e.get("timestamp"))
            )
            if rid not in spans:
                spans[rid] = [last_input, t, u.get("output_tokens") or 0]
            elif t:
                spans[rid][1] = t
            m = msg.get("model") or e.get("model")
            if rid not in seen_calls:
                seen_calls.add(rid)
                calls += 1
                if m:
                    models[m] += 1
                for k in (
                    "input_tokens",
                    "output_tokens",
                    "cache_creation_input_tokens",
                    "cache_read_input_tokens",
                ):
                    if isinstance(u.get(k), (int, float)):
                        tok[k] += u[k]
            for b in blocks_of(msg):
                bt = b.get("type")
                if bt == "thinking":
                    thinking_blocks += 1
                    thinking_chars += len(b.get("thinking") or "")
                    if b.get("thinking"):
                        thinking_texts.append((off, b.get("thinking")))
                    timeline.append(
                        (
                            off,
                            "model",
                            "thinking",
                            f"{len(b.get('thinking') or '')} chars",
                        )
                    )
                elif bt == "text":
                    txt = b.get("text") or ""
                    text_chars += len(txt)
                    if txt.strip():
                        last_text = txt
                    timeline.append((off, "model", "text", short(txt)))
                elif bt == "tool_use":
                    name = b.get("name") or "?"
                    tools[name] += 1
                    inp = b.get("input") or {}
                    if isinstance(inp, dict):
                        for k in ("file_path", "path", "notebook_path"):
                            if isinstance(inp.get(k), str):
                                files.add(inp[k])
                        record_write(writes, name, inp)
                        if name.lower() == "bash" and isinstance(
                            inp.get("command"), str
                        ):
                            commands.append(inp["command"])
                    timeline.append(
                        (off, "model", f"tool_use {name}", tool_arg(name, inp))
                    )
            if u and rid not in seen_usage_lines:
                seen_usage_lines.add(rid)
                timeline.append(
                    (
                        off,
                        "model",
                        "usage",
                        f"in {u.get('input_tokens', 0)} · out {u.get('output_tokens', 0)}"
                        + (
                            f" · cache read {u.get('cache_read_input_tokens')}"
                            if u.get("cache_read_input_tokens")
                            else ""
                        )
                        + (
                            f" · cache write {u.get('cache_creation_input_tokens')}"
                            if u.get("cache_creation_input_tokens")
                            else ""
                        ),
                    )
                )
        elif typ == "user" and msg:
            bl = blocks_of(msg)
            has_result = False
            for b in bl:
                if b.get("type") == "tool_result":
                    has_result = True
                    is_err = bool(b.get("is_error"))
                    if is_err:
                        errors += 1
                    content = b.get("content")
                    if isinstance(content, list):
                        content = " ".join(
                            (c.get("text") or "")
                            for c in content
                            if isinstance(c, dict)
                        )
                    timeline.append(
                        (
                            off,
                            "tool",
                            "result" + (" ERROR" if is_err else ""),
                            short(content or ""),
                        )
                    )
                elif b.get("type") == "text":
                    if not has_result and user_turns == 0 and "first_prompt" not in r:
                        r["first_prompt"] = (b.get("text") or "").strip()
                    timeline.append(
                        (off, "person", "prompt", short(clean_prompt(b.get("text"))))
                    )
            if not has_result and bl:
                user_turns += 1
            last_input = t or last_input
        elif typ in ("system", "summary", "progress"):
            continue

    r["models"] = dict(models)
    r["model_calls"] = calls
    r["user_turns"] = user_turns
    r["input_tokens"] = tok["input_tokens"]
    r["output_tokens"] = tok["output_tokens"]
    r["cache_read"] = tok["cache_read_input_tokens"]
    r["cache_write"] = tok["cache_creation_input_tokens"]
    r["thinking_blocks"] = thinking_blocks
    r["thinking_chars"] = thinking_chars
    r["text_chars"] = text_chars
    r["tools"] = dict(tools)
    r["tool_calls"] = sum(tools.values())
    r["files"] = sorted(files)
    r["commands"] = commands
    r["tool_errors"] = errors
    r["final_text"] = last_text
    r["timeline"] = timeline
    r["thinking_texts"] = thinking_texts
    r["logged_cost"] = 0.0
    r["harness_tally"] = harness_tally(ev)
    r["spans"] = [tuple(v) for v in spans.values()]
    r["writes"] = writes
    return r


def verb(kind):
    """Plain-language action labels for the trace."""
    if kind == "prompt":
        return "asks"
    if kind == "thinking":
        return "thinks"
    if kind == "text":
        return "says"
    if kind.startswith("tool_use "):
        return "runs " + kind.split(" ", 1)[1]
    if kind.startswith("result"):
        return "returns" + (" an error" if "ERROR" in kind else "")
    return kind


def fmt_secs(s):
    if s is None:
        return "?"
    m, sec = divmod(int(s), 60)
    return f"{m}m {sec:02d}s" if m else f"{sec}s"


def log_link(r, md_path, text=None):
    """A link the previewer can follow: relative to the report file when one is written, else file://."""
    text = text or r["file"]
    if md_path:
        rel = os.path.relpath(
            r["path"], os.path.dirname(os.path.abspath(md_path)) or "."
        )
        return f"[{text}]({rel.replace(' ', '%20')})"
    return f"[{text}](file://{r['path'].replace(' ', '%20')})"


def model_short(name):
    """claude-fable-5-1 -> fable-5; gemma4:26b -> gemma4; gpt-5 -> gpt-5; gemini-2.5-pro -> gemini-2.5"""
    m = (name or "").lower().split("/")[-1].split(":")[0]
    if m.startswith("claude-"):
        m = m[len("claude-") :]
    parts = m.split("-")
    out = []
    for part in parts:
        out.append(part)
        if part.replace(".", "").isdigit():
            break
    return "-".join(out) or m or "?"


def auto_label(r):
    h = "cc" if r["harness"] == "Claude Code" else r["harness"].lower()
    main = max(r["models"], key=r["models"].get) if r["models"] else r["file"]
    return f"{h}+{model_short(main)}"


def unique(names):
    """Suffix repeats with -2, -3, … so every column has its own name."""
    seen = Counter()
    out = []
    for n in names:
        seen[n] += 1
        out.append(f"{n}-{seen[n]}" if seen[n] > 1 else n)
    return out


# ---- Rubric for the infrastructure-stack prompt ------------------------------------------------
# Each row checks one requirement of the prompt, in the prompt's words. For a new assignment, copy this
# block, change STACK_FILE, RUBRIC_ROWS and stack_checks, and the rest of the report stays the same.
STACK_FILE = "stack*.md"  # stack.md, as the prompt asks; also matches older runs' stack-<harness-model>.md
WROTE, OWNERS, SOURCES, PHYSICAL, CONCISE = (
    "Writes a stack.md file",
    "Names the owner of each layer",
    "Cites a source for each claim",
    "Goes down to the physical facility",
    "Keeps it concise",
)
RUBRIC_ROWS = [WROTE, OWNERS, SOURCES, PHYSICAL, CONCISE]
NOT_WRITTEN = {WROTE: "\u274c no stack.md written"}
NO_VALUE = re.compile(r"^(unknown|n/?a|none|tbd|\?|-|\u2014)?$", re.I)
URL = re.compile(r"https?://")


def stack_output(r):
    """(full path, text, where the text came from) for the last stack*.md the run wrote, or None."""
    hits = [(p, c) for p, c in r["writes"] if fnmatch.fnmatch(os.path.basename(p), STACK_FILE)]
    if not hits:
        return None
    path = hits[-1][0]
    full = path if os.path.isabs(path) or not r.get("cwd") else os.path.join(r["cwd"], path)
    last_write = [c for p, c in hits if p == path][-1]
    if last_write is not None:
        # the content as the agent wrote it, unaffected by later changes to the file on disk
        return full, last_write, "as written in the log"
    if os.path.isfile(full):
        return full, open(full, encoding="utf-8").read(), "from disk"
    return full, None, "edited in place and no longer on disk"


def table_cells(line):
    line = line.strip()
    if not line.startswith("|"):
        return None
    return [c.strip() for c in line.strip("|").split("|")]


def plain(v):
    return re.sub(r"[*_`]", "", v or "").strip()


OWNER_ENTRY = re.compile(r"owner[*_\s]*[:\-\u2013]\s*(.+)", re.I)
SOURCE_ENTRY = re.compile(r"(?:source|basis|evidence|citation)s?[*_\s]*[:\-\u2013]\s*(.+)", re.I)
NOT_A_LAYER = re.compile(r"summary|caveat|limit|note|source|reference|conclusion|overview", re.I)


def layer_of(name, body):
    """(name, owner, source, has a link) from a layer's free text: its Owner: and Source: entries, or any link as the source."""
    o, src = OWNER_ENTRY.search(body), SOURCE_ENTRY.search(body)
    linked = bool(URL.search(body))
    return plain(name), plain(o.group(1)) if o else "", src.group(1) if src else (body if linked else ""), linked


def stack_layers(md):
    """(name, owner, source, has a link) per layer: one per row of a table with an Owner column, else one per heading
    (when the sections name owners), else one per top-level list item."""
    lines = md.splitlines()
    for i, line in enumerate(lines[:-1]):
        head = table_cells(line)
        if head and any("owner" in h.lower() for h in head) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):

            def col(pattern):
                return next((k for k, h in enumerate(head) if re.search(pattern, h, re.I)), None)

            owner, source, name = col("owner"), col("source|basis|evidence|citation|reference"), col("layer|name")
            layers = []
            for row in lines[i + 2 :]:
                c = table_cells(row)
                if c is None:
                    break
                cell = lambda k: c[k] if k is not None and k < len(c) else ""
                linked = bool(URL.search(row))
                layers.append((plain(cell(name) or c[0]), plain(cell(owner)), cell(source) or (row if linked else ""), linked))
            return layers
    sections = []
    for line in lines:
        h = re.match(r"^#{2,6}\s+(.+)", line)
        if h:
            sections.append([h.group(1), ""])
        elif sections:
            sections[-1][1] += line + "\n"
    sections = [(nm, body) for nm, body in sections if not NOT_A_LAYER.search(nm)]
    if len(sections) > 1 and any(OWNER_ENTRY.search(body) for _, body in sections):
        return [layer_of(re.sub(r"^\d+\.\s*", "", nm).split(":")[0], body) for nm, body in sections]
    blocks = []
    for line in lines:
        if re.match(r"^([-*+]|\d+\.)\s+\S", line):
            blocks.append(line)
        elif blocks and line.startswith((" ", "\t")) and line.strip():
            blocks[-1] += "\n" + line
        elif line.strip():
            blocks.append(None)  # a paragraph or heading ends the list
    return [layer_of(b.splitlines()[0].lstrip("-*+0123456789. ").split(":")[0], b) for b in blocks if b]


def mark(passed, total):
    """\u2705 all, \u26a0\ufe0f at least half, \u274c fewer than half."""
    return "\u2705" if total and passed == total else "\u26a0\ufe0f" if total and 2 * passed >= total else "\u274c"


def file_link(path, md_path):
    """The file's name, linked relative to the report when the file is still on disk."""
    name = os.path.basename(path)
    if not md_path or not os.path.isfile(path):
        return f"`{name}`"
    rel = os.path.relpath(path, os.path.dirname(os.path.abspath(md_path)))
    return f"[{name}]({rel.replace(' ', '%20')})"


def stack_facts(r):
    """What the rubric looks at in one run's write-up; written=False when there is no text to check."""
    out = stack_output(r)
    if out is None:
        return {"written": False, "path": None, "where": None}
    path, text, where = out
    if text is None:
        return {"written": False, "path": path, "where": where}
    layers = stack_layers(text)
    return {
        "written": True,
        "path": path,
        "where": where,
        "layers": len(layers),
        "owned": sum(1 for _, o, _, _ in layers if not NO_VALUE.match(plain(o))),
        "sourced": sum(1 for _, _, s, _ in layers if not NO_VALUE.match(plain(s))),
        "linked": sum(1 for *_, has_link in layers if has_link),
        "physical": any(re.search(r"physical|facilit|data ?cent|building", nm, re.I) for nm, *_ in layers),
        "words": len(text.split()),
    }


def stack_checks(r, md_path=None):
    """Rubric cells for one run, keyed by row name."""
    f = stack_facts(r)
    if f["path"] is None:
        return NOT_WRITTEN
    name = file_link(f["path"], md_path)
    if not f["written"]:
        return {WROTE: f"❌ {name} ({f['where']})"}
    n = f["layers"]
    return {
        WROTE: f"✅ {name}" + ("" if f["where"] == "as written in the log" else f" ({f['where']})"),
        OWNERS: f"{mark(f['owned'], n)} {f['owned']} of {n} layers",
        SOURCES: f"{mark(f['sourced'], n)} {f['sourced']} of {n} layers"
        + (f" ({f['linked']} with a web link)" if f["sourced"] else ""),
        PHYSICAL: "✅ Yes" if f["physical"] else "❌ No",
        CONCISE: f"{f['words']:,} words",
    }


def group_checks(group, md_path=None):
    """Rubric cells for a setup's runs: for one run its details, for several how many runs passed each check."""
    if len(group) == 1:
        return stack_checks(group[0], md_path)
    facts = [stack_facts(r) for r in group]
    if not any(f["path"] for f in facts):
        return NOT_WRITTEN
    k = len(facts)
    ok = [f for f in facts if f["written"]]

    def passed(test):
        n = sum(1 for f in ok if test(f))
        return f"{mark(n, k)} {n} of {k} runs"

    return {
        WROTE: passed(lambda f: True),
        OWNERS: passed(lambda f: f["layers"] and f["owned"] == f["layers"]),
        SOURCES: passed(lambda f: f["layers"] and f["sourced"] == f["layers"])
        + f" (web links in {sum(1 for f in ok if f['linked'])} of {k})",
        PHYSICAL: passed(lambda f: f["physical"]),
        CONCISE: spread([f["words"] for f in ok], lambda x: f"{x:,.0f}") + " words" if ok else "",
    }


def output_checks(groups, headers, w, md_path=None):
    """A second table grading the stack*.md write-ups; left out when no run wrote one."""
    checks = [group_checks(g, md_path) for g in groups]
    if all(c == NOT_WRITTEN for c in checks):
        return
    w("## How good are the results?\n")
    w("Each row is a requirement from the prompt, checked automatically. The checks test structure, not whether it is true.\n")
    w("| | " + " | ".join(headers) + " |")
    w("|---|" + "---|" * len(headers))
    for key in RUBRIC_ROWS:
        w(f"| **{key}** | " + " | ".join(c.get(key, "") for c in checks) + " |")
    w("")


def spread(values, fmt, unit=""):
    """One value as is; several as median (lowest–highest), with the unit once. None values are left out."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return "?"
    if len(vals) == 1:
        return fmt(vals[0]) + unit
    # the median in bold is the value to read; the range in brackets is the detail
    return f"**{fmt(statistics.median(vals))}{unit}** ({fmt(vals[0])}–{fmt(vals[-1])})"


def dollars(x):
    """$1.23 with the $ escaped, for Markdown outside code format."""
    return "\\$" + f"{x:.2f}"


def throughput_value(r):
    """Output tokens per second of waiting on the model; the wait includes reading the prompt, not just writing."""
    spans = [(a, b, n) for a, b, n in r["spans"] if a and b and b > a]
    secs = sum((b - a).total_seconds() for a, b, _ in spans)
    toks = sum(n for _, _, n in spans)
    return toks / secs if secs and toks else None


def run_number(r):
    """The N of a run.py run folder (runs/<setup>/runN), or None."""
    parts = run_parts(r.get("cwd"))
    return parts[1] if parts else None


def simple_report(groups, labels, headers, prices, timeline, md_path=None):
    out = []
    w = out.append

    def first(r, pred):
        for off, who, kind, detail in r["timeline"]:
            if pred(who, kind):
                return off
        return None

    def tally(r):
        t = r.get("harness_tally")
        if t is None:
            return ""
        if is_local(r["models"]):
            return (
                f"; the harness’s own tally says ${t:.2f}, a phantom price for unbilled tokens"
                if t
                else ""
            )
        return f"; the harness’s own tally says ${t:.2f}"

    def cost_value(lab, r):
        """Dollars at API list prices, 0 for a local model, None when the model has no price."""
        if is_local(r["models"]):
            return 0.0
        main_model = max(r["models"], key=r["models"].get) if r["models"] else ""
        p = prices.get(lab) or price_for(main_model)
        if p:
            return cost_breakdown(r, p)[0]
        return r.get("logged_cost") or None

    def cost_core(lab, r):
        if is_local(r["models"]):
            return "$0"
        main_model = max(r["models"], key=r["models"].get) if r["models"] else ""
        p = prices.get(lab) or price_for(main_model)
        if p:
            total, parts = cost_breakdown(r, p)
            top = sorted(parts.items(), key=lambda kv: -kv[1])[:3]
            return "$%.2f (%s)" % (total, ", ".join(f"{k} ${v:.2f}" for k, v in top))
        if r.get("logged_cost"):
            return "$%.2f (from log)" % r["logged_cost"]
        return "not priced: pass --price " + lab + "=IN,OUT"

    def cost(lab, g):
        """The Cost cell. One run keeps its code-formatted breakdown; several runs use bold, which code
        format would hide, with $ escaped so Markdown previews don't read $…$ as math."""
        if len(g) == 1:
            return "`" + cost_core(lab, g[0]) + tally(g[0]) + "`"
        vals = [cost_value(lab, r) for r in g]
        if any(v is None for v in vals):
            return "`" + cost_core(lab, g[0]) + "`"
        if not any(vals):
            return "`$0`"
        return f"{spread(vals, dollars)} per run · {dollars(sum(vals))} for {len(g)} runs"

    def looked_tools(r):
        # tools the model ran before it first wrote a file or gave its final answer
        seen = []
        for off, who, kind, detail in r["timeline"]:
            if kind.startswith("tool_use"):
                name = kind.split(" ", 1)[1]
                if name.lower() in ("write", "edit", "multiedit") or (
                    name.lower() == "bash" and ("cat >" in detail or "tee " in detail)
                ):
                    break
                seen.append(name)
        return seen

    def looked(g):
        if len(g) == 1:
            return ", ".join(looked_tools(g[0])) or "No"
        tools = [looked_tools(r) for r in g]
        n = sum(1 for t in tools if t)
        if not n:
            return "No"
        common = [name for name, _ in Counter(x for t in tools for x in t).most_common(3)]
        return f"{n} of {len(g)} runs, mostly {', '.join(common)}"

    def sent(r):
        return r["input_tokens"] + r["cache_read"] + r["cache_write"]

    def per_call(g):
        if len(g) == 1:
            r = g[0]
            n = max(r["model_calls"], 1)
            return f"{sent(r) // n:,} per call, {int(100 * r['cache_read'] / sent(r)) if sent(r) else 0}% from cache ({sent(r):,} over {n} call{'s' if n != 1 else ''})"
        total = sum(sent(r) for r in g)
        cached = sum(r["cache_read"] for r in g)
        return (
            spread([sent(r) / max(r["model_calls"], 1) for r in g], lambda x: f"{x:,.0f}")
            + f" per call, {int(100 * cached / total) if total else 0}% from cache"
        )

    def actions(g):
        if len(g) == 1:
            r = g[0]
            return (
                f"{r['user_turns']} prompt{'s' if r['user_turns'] != 1 else ''} · {r['model_calls']} model calls · {r['tool_calls']} tool call{'s' if r['tool_calls'] != 1 else ''}"
                + (f" ({r['tool_errors']} failed)" if r["tool_errors"] else "")
            )
        failed = sum(r["tool_errors"] for r in g)
        return (
            spread([r["model_calls"] for r in g], lambda x: f"{x:.0f}")
            + " model calls · "
            + spread([r["tool_calls"] for r in g], lambda x: f"{x:.0f}")
            + " tool calls"
            + (f" ({failed} failed across runs)" if failed else "")
        )

    def output_note(r, estimate=True):
        if r["thinking_chars"] and not is_local(r["models"]):
            return ", reasoning included."
        if r["thinking_chars"] and estimate:
            return f". About {int(round(r['thinking_chars'] / 4, -2)):,} of them reasoning, shown in the log."
        if r["thinking_chars"]:
            return ". Reasoning shown in the log."
        if r["thinking_blocks"]:
            return ". Reasoning not shown in the log."
        return "."

    def output_of(g):
        if len(g) == 1:
            return f"{g[0]['output_tokens']:,} tokens" + output_note(g[0])
        return spread([r["output_tokens"] for r in g], lambda x: f"{x:,.0f}") + " tokens" + output_note(g[0], estimate=False)

    def reasoning_kind(r):
        if not r["thinking_blocks"] and not r["thinking_chars"]:
            return "None recorded"
        if is_local(r["models"]):
            return (
                "Full chain, as the model wrote it"
                if r["thinking_chars"]
                else "None recorded"
            )
        if r["thinking_chars"]:
            return "Summary written by the provider, not the full chain"
        if r["harness"] == "Claude Code":
            return "Not logged: empty blocks. Set `showThinkingSummaries` to log a summary"
        return "Not logged: empty blocks"

    def where(r):
        if is_local(r["models"]):
            return "stayed on this machine; nothing left it"
        names = json.dumps(r["models"]).lower()
        who = (
            "Anthropic"
            if "claude" in names
            else "OpenAI"
            if "gpt" in names or "o1" in names or "o3" in names
            else "Google"
            if "gemini" in names
            else "the model provider"
        )
        seen = []
        if r["tool_calls"]:
            seen.append(
                "every tool result"
                + (
                    " (file contents, command output)"
                    if r["files"] or r["commands"]
                    else ""
                )
            )
        return (
            f"to {who}: the prompt, the harness context"
            + (", " + seen[0] if seen else "")
            + ", per the provider’s retention terms"
        )

    w("# Agent run report\n")
    prompt = next((r.get("first_prompt") for g in groups for r in g if r.get("first_prompt")), None)
    if prompt:
        w("Prompt:\n")
        w("> " + clean_prompt(prompt) + "\n")
    if any(len(g) > 1 for g in groups):
        w(
            "With several runs, the **bold** value is the median: the middle run, not the best or the average. "
            "Brackets show the lowest and highest run.\n"
        )
    w("| | " + " | ".join(headers) + " |")
    w("|---|" + "---|" * len(headers))

    def row(name, vals):
        w(f"| **{name}** | " + " | ".join(str(v) for v in vals) + " |")

    row("Latency", [spread([first(r, lambda who, k: who == "model") for r in g], fmt_secs) for g in groups])
    row("Total time", [spread([r["wall_seconds"] for r in g], fmt_secs) for g in groups])
    row("Throughput", [spread([throughput_value(r) for r in g], lambda x: f"{x:,.0f}", " tokens/s") for g in groups])
    row("Actions", [actions(g) for g in groups])
    row("Looked before answering", [looked(g) for g in groups])
    row("Input tokens", [per_call(g) for g in groups])
    row("Output tokens", [output_of(g) for g in groups])
    row("Reasoning in the log", [Counter(reasoning_kind(r) for r in g).most_common(1)[0][0] for g in groups])
    row("Where the data went", [where(g[0]) for g in groups])
    row("Cost", [cost(lab, g) for lab, g in zip(labels, groups)])
    w("")
    output_checks(groups, headers, w, md_path)
    w("## Your evaluation\n")
    w(
        "Where does your judgment disagree with the checks above? That gap is what automated evaluation misses. "
        "Read each agent's write-up and trace, then fill in:\n"
    )
    w("| | " + " | ".join(headers) + " |")
    w("|---|" + "---|" * len(headers))
    for q in [
        "Are the facts right and backed by the sources?",
        "Anything made up or overclaimed?",
        "Which would you trust, and why?",
    ]:
        w(f"| **{q}** |" + " |" * len(headers))
    w("")
    w(
        "> ⚠️ \U0001f3b2 **One run per setup is one sample.** Agents vary from run to run, so a fair comparison "
        "repeats each setup **3–5 times with the same prompt**.\n"
    )
    w("## Traces\n")
    who_icon = {"person": "\U0001f9d1 you", "model": "\U0001f916 model", "tool": "\U0001f527 tool"}
    for head, g in zip(headers, groups):
        base = re.sub(r" \(\d+ runs\)$", "", head)
        for r in g:
            n = run_number(r)
            text = f"Log file for {base}" + (f", run {n}" if len(g) > 1 and n else "")
            w(log_link(r, md_path, text) + "\n")
            if not timeline:
                continue
            steps = [
                (off, who, kind, detail)
                for off, who, kind, detail in r["timeline"]
                if kind != "usage" and not (kind == "thinking" and detail.startswith("0 "))
            ]
            w(f"<details>\n<summary>{len(steps)} steps</summary>\n")
            w("| Time | Who | Did | Detail |")
            w("|---|---|---|---|")
            for off, who, kind, detail in steps:
                cell = " ".join(detail.split()).replace("|", "\\|").replace("`", "'") or "(empty)"
                w(f"| {fmt_secs(off)} | {who_icon.get(who, who)} | {verb(kind)} | {cell} |")
            w("\n</details>\n")
        w("---\n")
    return "\n".join(out)


CC_ROOT = os.path.expanduser("~/.claude/projects")
PI_ROOT = os.path.expanduser("~/.pi/agent/sessions")
PICK_LIMIT = 10  # setup folders shown per list


def session_files(root):
    """Session logs directly inside root's project folders, newest first. Nested logs (sub-agents) are left out."""
    base = os.path.realpath(root)
    found = []
    for p in glob.glob(os.path.join(base, "*", "*.jsonl")):
        real = os.path.realpath(p)
        # a symlink pointing outside the log folder is not a session log
        if os.path.commonpath([base, real]) != base or not os.path.isfile(real):
            continue
        found.append((os.path.getmtime(real), real))
    return [p for _, p in sorted(found, reverse=True)]


# Wrappers the harnesses put around what a person typed. System reminders go entirely; the others keep their inside text.
HARNESS_NOTE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
HARNESS_TAG = re.compile(r"</?(?:pasted_content|command-name|command-message|command-args)\b[^>]*>")


def clean_prompt(txt):
    """The prompt as the person wrote it, on one line."""
    return " ".join(HARNESS_TAG.sub(" ", HARNESS_NOTE.sub(" ", txt or "")).split())


def prompt_text(e):
    """The text a person typed, from one log line of either harness; None for tool results and harness notes."""
    msg = e.get("message")
    if e.get("isMeta") or not isinstance(msg, dict) or msg.get("role") != "user":
        return None
    txt = clean_prompt(" ".join(b.get("text") or "" for b in blocks_of(msg) if b.get("type") == "text"))
    return txt or None


def run_summary(path):
    """Project name, first prompt, model provider and working folder, reading only as far as the first prompt."""
    cwd, prompt, provider = None, None, None
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(e, dict):
                continue
            cwd = cwd or e.get("cwd")
            if e.get("type") == "model_change":  # pi names the provider before the first prompt
                provider = e.get("provider")
            prompt = prompt_text(e)
            if prompt:
                break
    project = os.path.basename(cwd) if cwd else os.path.basename(os.path.dirname(path))
    return project, prompt or "(no prompt)", provider, cwd


# The lab's three setups, in the order the report shows them: neighbors differ in one part only.
LOCAL_PROVIDERS = {"ollama"}
# Each entry: list title, log folder, which logs belong, and the run.py command that makes a run of it.
SETUP_PICKS = [
    ("Setup 1 \u00b7 Claude Code", CC_ROOT, lambda provider: True, "python3 run.py claude"),
    (
        "Setup 2 \u00b7 pi with a cloud model",
        PI_ROOT,
        lambda provider: provider not in LOCAL_PROVIDERS,
        "python3 run.py pi --provider anthropic --model claude-opus-5-5",
    ),
    ("Setup 3 \u00b7 pi with a local model", PI_ROOT, lambda provider: provider in LOCAL_PROVIDERS, "python3 run.py pi"),
]
def run_parts(cwd):
    """(setup folder, run number) when cwd is a run.py run folder, …/runs/<setup>/runN; otherwise None."""
    parts = os.path.normpath(cwd or "").split(os.sep)
    m = re.fullmatch(r"run(\d+)", parts[-1]) if len(parts) >= 3 and parts[-3] == "runs" else None
    return (parts[-2], int(m.group(1))) if m else None


def run_logs():
    """Every run.py run whose folder still exists: {run folder: (log path, provider)}, newest log per folder.
    Other sessions, like a live conversation, are left out, and deleting a run folder drops its run."""
    found = {}
    for root in (CC_ROOT, PI_ROOT):
        for p in session_files(root):
            _, _, provider, cwd = run_summary(p)
            if run_parts(cwd) and os.path.isdir(cwd) and cwd not in found:
                found[cwd] = (p, provider)
    return found


def runs_in(folder, logs):
    """Log paths for a setup folder (all its runs, in run order) or a single run folder."""
    folder = os.path.abspath(folder)
    if run_parts(folder):
        return [logs[folder][0]] if folder in logs else []
    mine = [(run_parts(cwd)[1], p) for cwd, (p, _) in logs.items() if os.path.dirname(cwd) == folder]
    return [p for _, p in sorted(mine)]


def pick(title, root, interactive, logs, keep=lambda provider: True):
    """List the setup folders that fit one setup, newest first; ask for one when interactive.
    Returns its runs' log paths, [] when there are none, None when not interactive."""
    folders = {}  # setup folder -> [(run number, log path)]
    for cwd, (p, provider) in logs.items():
        if p.startswith(root) and keep(provider):
            folders.setdefault(os.path.dirname(cwd), []).append((run_parts(cwd)[1], p))
    order = sorted(folders, key=lambda f: -max(os.path.getmtime(p) for _, p in folders[f]))[:PICK_LIMIT]
    print(f"\n{title}:")
    if not order:
        print("  none yet")
        return []
    for i, f in enumerate(order, 1):
        runs = folders[f]
        when = datetime.fromtimestamp(max(os.path.getmtime(p) for _, p in runs)).strftime("%b %d %H:%M")
        name = os.path.relpath(f, os.getcwd()) if not interactive else os.path.basename(f)
        print(f"  {i:>2}  {name:36}  {len(runs):>2} run{'s' if len(runs) != 1 else ' '}  last {when}")
    if not interactive:
        return None
    while True:
        try:
            ans = input("Pick a folder [1]: ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)
        if ans.isdigit() and 1 <= int(ans) <= len(order):
            return [p for _, p in sorted(folders[order[int(ans) - 1]])]
        print(f"Enter a number from 1 to {len(order)}.")


def pick_logs():
    """The runs to compare, one group per setup, chosen by setup folder. Without a terminal to ask in, print the lists and exit."""
    interactive = sys.stdin.isatty()
    if interactive:
        print("\nPick a folder of runs for each setup: type its number and press Enter (Enter alone picks 1, the newest).")
    logs = run_logs()
    groups = []
    for title, root, keep, how in SETUP_PICKS:
        chosen = pick(title, root, interactive, logs, keep)
        if chosen == []:
            sys.exit(f"\n{title} has no runs yet. Make one first:\n  {how}")
        groups.append(chosen)
    if not interactive:
        print(
            "\nNo terminal to ask in, so nothing was picked. Pass the folders above, in setup order:\n"
            "  python3 report.py runs/SETUP1 runs/SETUP2 runs/SETUP3"
        )
        sys.exit(0)
    print("\nComparing:")
    for (title, *_), g in zip(SETUP_PICKS, groups):
        print(f"  {title}: {len(g)} run{'s' if len(g) != 1 else ''}")
    print()
    return groups


def arg_groups(paths):
    """Command-line inputs as report columns: a log file on its own, or a run.py folder with its runs."""
    logs = None
    groups = []
    for path in paths:
        if os.path.isdir(path):
            logs = logs if logs is not None else run_logs()
            found = runs_in(path, logs)
            if not found:
                sys.exit(f"No run.py runs found in {path}")
            groups.append(found)
        else:
            groups.append([path])
    return groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "logs",
        nargs="*",
        help="session logs or run folders to compare, one column each; leave out to pick a folder per setup",
    )
    ap.add_argument("--label", action="append", default=[])
    ap.add_argument(
        "--price",
        action="append",
        default=[],
        help="LABEL=IN,OUT in USD per million tokens",
    )
    ap.add_argument(
        "--no-timeline",
        action="store_true",
        help="leave the per-run traces out of the report",
    )
    ap.add_argument(
        "--full",
        action="store_true",
        help="the detailed report: every counter and every event",
    )
    ap.add_argument(
        "--md",
        default="report.md",
        help="where to write the report (default report.md; use - for stdout only)",
    )
    a = ap.parse_args()
    # one column per group: a setup folder's runs, or a log file given on the command line
    groups = [[analyze(p) for p in g] for g in (pick_logs() if not a.logs else arg_groups(a.logs))]
    labels = unique(
        [a.label[i] if i < len(a.label) else auto_label(g[0]) for i, g in enumerate(groups)]
    )
    # columns are headed harness · model unless the person named them
    headers = unique(
        [
            a.label[i]
            if i < len(a.label)
            else f"{g[0]['harness']} · {max(g[0]['models'], key=g[0]['models'].get) if g[0]['models'] else '?'}"
            + (f" ({len(g)} runs)" if len(g) > 1 else "")
            for i, g in enumerate(groups)
        ]
    )
    prices = {}
    for p in a.price:
        k, v = p.split("=", 1)
        nums = [float(x) for x in v.split(",")]
        if len(nums) == 2:
            nums += [nums[0] * 1.25, nums[0] * 0.1]
        prices[k] = tuple(nums[:4])

    if not a.full:
        md = None if a.md == "-" else a.md
        text = simple_report(groups, labels, headers, prices, not a.no_timeline, md)
        print(text)
        if md:
            with open(md, "w", encoding="utf-8") as f:
                f.write(text)
            sys.stderr.write(f"wrote {md}\n")
        return

    # the detailed report keeps one column per run, even for a setup picked with several runs
    runs = [r for g in groups for r in g]
    if len(runs) != len(groups):
        labels = unique([auto_label(r) for r in runs])
    out = []
    w = out.append
    w("# Trace comparison\n")
    head = "| | " + " | ".join(labels) + " |"
    w(head)
    w("|---|" + "---|" * len(labels))

    def row(name, vals):
        w(f"| {name} | " + " | ".join(str(v) for v in vals) + " |")

    row("Log file", [r["file"] for r in runs])
    row("Harness", [r["harness"] for r in runs])
    row(
        "Model(s)",
        [", ".join(f"{k} ×{v}" for k, v in r["models"].items()) or "?" for r in runs],
    )
    row("Wall clock", [fmt_secs(r["wall_seconds"]) for r in runs])
    row("Person turns", [r["user_turns"] for r in runs])
    row("Model calls", [r["model_calls"] for r in runs])
    row("Tool calls", [r["tool_calls"] for r in runs])
    row(
        "Tools used",
        [
            ", ".join(
                f"{k} ×{v}"
                for k, v in sorted(r["tools"].items(), key=lambda kv: -kv[1])
            )
            or "none"
            for r in runs
        ],
    )
    row("Tool errors", [r["tool_errors"] for r in runs])
    row("Files touched", [len(r["files"]) for r in runs])
    row("Input tokens", [f"{r['input_tokens']:,}" for r in runs])
    row("Output tokens", [f"{r['output_tokens']:,}" for r in runs])
    row(
        "Cache read / write",
        [f"{r['cache_read']:,} / {r['cache_write']:,}" for r in runs],
    )
    row(
        "Thinking blocks (chars)",
        [f"{r['thinking_blocks']} ({r['thinking_chars']:,})" for r in runs],
    )
    row("Visible text (chars)", [f"{r['text_chars']:,}" for r in runs])
    costs = []
    for lab, r in zip(labels, runs):
        main_model = max(r["models"], key=r["models"].get) if r["models"] else ""
        p = prices.get(lab) or (
            None if is_local(r["models"]) else price_for(main_model)
        )
        if p:
            c, parts = cost_breakdown(r, p)
            costs.append(
                f"${c:.4f} ("
                + ", ".join(f"{k} ${v:.4f}" for k, v in parts.items())
                + ")"
            )
        elif is_local(r["models"]):
            costs.append("no bill")
        elif r.get("logged_cost"):
            costs.append(f"${r['logged_cost']:.4f} (from log)")
        else:
            costs.append(
                "not priced"
                if r["input_tokens"] or r["output_tokens"]
                else "no usage in log"
            )
    row("Cost", ["`" + c + "`" for c in costs])
    w("")
    output_checks([[r] for r in runs], labels, w, None if a.md == "-" else a.md)
    for lab, r in zip(labels, runs):
        w(f"## {lab}\n")
        if r["files"]:
            w("Files touched:")
            for f in r["files"]:
                w(f"- `{f}`")
        if r["commands"]:
            w("\nCommands run:")
            for c in r["commands"]:
                w(f"- `{short(c, 120)}`")
        if r.get("thinking_texts"):
            w("\nRecorded reasoning, in full:\n")
            for off, txt in r["thinking_texts"]:
                w(f"At {fmt_secs(off)}:\n")
                w("> " + " ".join(txt.split()).replace("\n", "\n> "))
                w("")
        w("\nFinal message:\n")
        w(
            "> "
            + (
                r["final_text"].strip().replace("\n", "\n> ")
                if r["final_text"]
                else "(none)"
            )
        )
        w("")
        if not a.no_timeline:
            w("Timeline:\n")
            w("```")
            w(f"{'sec':>7}  {'who':6}  {'action':22}  detail")
            for off, who, kind, detail in r["timeline"]:
                w(
                    f"{('%7.1f' % off) if off is not None else '      ?'}  {who:6}  {(kind if kind == 'usage' else verb(kind)):22}  {detail}"
                )
            w("```\n")

    text = "\n".join(out)
    print(text)
    if a.md != "-":
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(text)
        sys.stderr.write(f"wrote {a.md}\n")


if __name__ == "__main__":
    main()
