#!/usr/bin/env python3
"""
mva: a minimum viable agent harness.

One file, standard library only (Python 3.11+). Each section below is one box
of the agent architecture: context, router, model call, result, tool,
guardrail, the loop, and the trace. Triggers decide what begins each run.

A setup is a folder in setups/ with two files:
  spec.md       what the model reads (requested)
  harness.toml  what this program enforces (enforced)

Two settings in harness.toml place the setup on the Autonomy Grid:
  path    = "steps" | "goal"                 who picks the next step
  trigger = "manual" | "every" | "on_new_file"   what begins each run

Usage:
  python mva.py run   setups/task-agent
  python mva.py reset setups/task-agent
  python mva.py usage
  python mva.py usage --runs
  python mva.py golden setups/task-agent [--force]
  python mva.py eval   setups/task-agent [--runs 20] [--model openai/gpt-5-mini] [--jobs 4] [--allow-unverified]
"""
import base64
import csv
import io
import json
import math
import os
import re
import shutil
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RECEIPTS = ROOT / "receipts"
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
TEXT_TYPES = {".txt", ".md", ".csv", ".log", ".json", ".toml"}


# ---------------------------------------------------------------- terminal
# Bold, dim and plain red, plus two fixed 256-palette colors: themes redraw the basic colors, so
# bright ones vanish on a light background and dark ones on a dark background. Jade #00875f and
# rust #af5f5f keep about 4.5:1 contrast on both white and black. The leading symbol carries the meaning.
STYLES = {"run": "1", "done": "1", "ask": "1", "notify": "1", "denied": "31", "model": "2", "tick": "2",
          "ok": "1;38;5;29", "failed": "1;38;5;131"}
LOCAL = threading.local()  # an eval runs several agents at once: each thread's lines start with its run's name


def styled():
    """Escape codes only in a terminal, and never when NO_COLOR is set."""
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def say(kind, text):
    style = STYLES.get(kind)
    text = getattr(LOCAL, "prefix", "") + text
    print(f"\033[{style}m{text}\033[0m" if style and styled() else text, flush=True)


# ---------------------------------------------------------------- 0. the agent
class Agent:
    """Loads spec.md (requested) and harness.toml (enforced) from a folder."""

    def __init__(self, folder):
        self.dir = Path(folder).resolve()
        self.name = self.dir.name
        self.spec = (self.dir / "spec.md").read_text()
        self.cfg = tomllib.loads((self.dir / "harness.toml").read_text())
        c = self.cfg
        self.path = c.get("path", "goal")
        self.trigger = c.get("trigger", "manual")
        # MVA_MODEL, from the environment or .env, overrides every setup, so nobody edits harness.toml for it
        self.model = os.environ.get("MVA_MODEL") or dotenv().get("MVA_MODEL") or c.get("model", "anthropic/claude-sonnet-5")
        self.tools = c.get("tools", [])
        self.deny = c.get("deny", [])
        self.read = c.get("read", [])
        self.write = c.get("write", [])
        self.memory = c.get("memory")
        self.ask_queue = c.get("ask_queue", "pending")
        self.max_turns = c.get("max_turns", 30)
        self.max_seconds = c.get("max_seconds", 300)
        self.answers = None  # set by eval: scripted answers from golden.jsonl, so ask never waits for a person

    def file(self, rel):
        """Resolve a path the model gives us. It must stay inside the agent folder."""
        p = (self.dir / rel).resolve()
        if self.dir not in p.parents and p != self.dir:
            raise PermissionError(f"{rel} is outside the agent folder")
        return p


# ---------------------------------------------------------------- 8. trace
OPEN_TRACES = []  # runs not closed yet: main closes them if a run is cut short


class Trace:
    """Every run leaves a file: traces/<time>.jsonl. Evaluation reads these."""

    def __init__(self, agent, label):
        self.agent = agent
        (agent.dir / "traces").mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = agent.dir / "traces" / f"{stamp}-{label}.jsonl"
        self.label = label
        self.start = time.time()
        self.tokens_in = self.tokens_out = self.calls = 0
        OPEN_TRACES.append(self)

    def log(self, event, **data):
        with self.path.open("a") as f:
            f.write(json.dumps({"t": round(time.time() - self.start, 2), "event": event, **data}) + "\n")

    def usage(self, tin, tout):
        self.calls += 1
        self.tokens_in += tin
        self.tokens_out += tout

    def close(self, outcome):
        OPEN_TRACES.remove(self)
        secs = round(time.time() - self.start, 1)
        summary = {"agent": self.agent.name, "path": self.agent.path, "trigger": self.agent.trigger,
                   "model": self.agent.model, "model_calls": self.calls, "tokens_in": self.tokens_in,
                   "tokens_out": self.tokens_out, "seconds": secs, "outcome": outcome,
                   "time": datetime.now().isoformat(timespec="seconds"), "label": self.label}
        self.log("end", **summary)
        with (self.agent.dir / "traces" / "summary.jsonl").open("a") as f:
            f.write(json.dumps(summary) + "\n")
        dollars = cost(self.agent.model, self.tokens_in, self.tokens_out)
        say("ok" if mark(outcome) == "✓" else "failed", f"{mark(outcome)} {outcome} · {self.calls} model calls · {self.tokens_in:,} tokens in · "
                    f"{self.tokens_out:,} out · {secs}s · {money(dollars)} · trace: {self.path.relative_to(ROOT)}")


# ---------------------------------------------------------------- content blocks
# Inside the harness, content is a list of blocks: {"type": "text", "text": ...},
# {"type": "image", "media_type": ..., "data": <base64>}, or the same shape with
# "type": "document" for a PDF. Each backend converts.

def text(s):
    return {"type": "text", "text": s}


def file_blocks(agent, p):
    ext = p.suffix.lower()
    if ext in IMAGE_TYPES:
        return [text(f"[image: {p.name}]"),
                {"type": "image", "media_type": IMAGE_TYPES[ext], "data": base64.b64encode(p.read_bytes()).decode()}]
    if ext == ".pdf":  # only the Anthropic API reads PDFs here
        if route(agent.model)[0] != "anthropic":
            return [text(f"{p.name}: this model cannot read PDFs. Use an anthropic/ model, or convert the PDF to text.")]
        return [text(f"[pdf: {p.name}]"),
                {"type": "document", "media_type": "application/pdf", "data": base64.b64encode(p.read_bytes()).decode()}]
    if ext in TEXT_TYPES:
        return [text(p.read_text()[:20000])]
    return [text(f"{p.name}: this harness cannot read {ext} files.")]


# ---------------------------------------------------------------- 1. context
def assemble_context(agent, trace, first_message):
    """Everything the model reads: its instructions, the spec, memory, tool descriptions."""
    parts = [agent.spec]
    if agent.memory:
        mem = agent.file(agent.memory)
        notes = mem.read_text() if mem.exists() else "(empty: this is the first run)"
        parts.append(f"# Your memory ({agent.memory}), written by your earlier runs\n\n{notes}")
    tools = offered_tools(agent)
    if agent.path == "goal" and tool_mode(agent) == "text":
        parts.append(text_protocol(tools))
    system = "\n\n".join(parts)
    trace.log("context", spec_chars=len(agent.spec), memory_chars=len(parts[1]) if agent.memory else 0,
              tools=[t for t in tools], system_chars=len(system))
    return system, [{"role": "user", "content": first_message}]


# ---------------------------------------------------------------- 2. router
KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY"}  # ollama runs on your computer and needs none


def route(model):
    """'anthropic/claude-sonnet-5' · 'openai/gpt-5-mini' · 'gemini/gemini-2.5-flash' · 'ollama/gemma3'
    · 'openrouter/<vendor>/<model>'"""
    provider, _, name = model.partition("/")
    if provider == "anthropic":
        return "anthropic", name, "https://api.anthropic.com/v1/messages"
    if provider == "ollama":
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        return "openai", name, host.rstrip("/") + "/v1/chat/completions"
    if provider == "openai":
        return "openai", name, "https://api.openai.com/v1/chat/completions"
    if provider == "gemini":
        return "openai", name, "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    if provider == "openrouter":
        return "openai", name, "https://openrouter.ai/api/v1/chat/completions"
    raise ValueError(f"unknown provider in model '{model}': use anthropic/, openai/, gemini/, ollama/ or openrouter/")


def tool_mode(agent):
    """native: the API carries tool calls. text: the model writes JSON and we parse it."""
    if "tool_mode" in agent.cfg:
        return agent.cfg["tool_mode"]
    return "text" if agent.model.startswith("ollama/") else "native"


# ---------------------------------------------------------------- 3. model call
def call_model(agent, trace, system, messages, tools):
    kind, name, url = route(agent.model)
    native = bool(tools) and tool_mode(agent) == "native"
    if kind == "anthropic":
        body = {"model": name, "max_tokens": 4096, "system": system, "messages": to_anthropic(messages, native)}
        if native:
            body["tools"] = [{"name": n, "description": TOOLS[n]["about"], "input_schema": schema(n)} for n in tools]
        headers = {"x-api-key": need_key(KEYS["anthropic"]), "anthropic-version": "2023-06-01"}
    else:
        body = {"model": name, "messages": [{"role": "system", "content": system}] + to_openai(messages, native)}
        if native:
            body["tools"] = [{"type": "function", "function": {"name": n, "description": TOOLS[n]["about"],
                                                               "parameters": schema(n)}} for n in tools]
        headers = {}
        provider = agent.model.partition("/")[0]
        if provider in KEYS:
            headers["Authorization"] = "Bearer " + need_key(KEYS[provider])
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json", **headers})
    say("model", f"  → {agent.model} · {len(messages)} messages in context")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"model call failed ({e.code}): {e.read().decode()[:600]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"cannot reach {url}: {e.reason}")
    return parse_result(agent, trace, kind, data, native)


def need_key(var):
    """A key set in the environment wins; otherwise it comes from .env next to mva.py."""
    key = os.environ.get(var) or dotenv().get(var)
    if not key:
        raise SystemExit(f"no {var}: copy .env.example to .env and paste your key after {var}=")
    return key


def dotenv():
    """KEY=value lines. Outside every agent folder, so no agent's tools can read it."""
    env = ROOT / ".env"
    pairs = {}
    if env.exists():
        for line in env.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and not k.strip().startswith("#"):
                pairs[k.strip()] = v.strip().strip("\"'")
    return pairs


def to_anthropic(messages, native):
    out = []
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": [a_block(b) for b in m["content"]]})
        elif m["role"] == "assistant":
            content = [{"type": "text", "text": m["text"]}] if m.get("text") else []
            if native:
                content += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]} for c in m["calls"]]
            out.append({"role": "assistant", "content": content or [{"type": "text", "text": "."}]})
        elif m["role"] == "tool":
            if native:
                out.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": r["id"], "content": [a_block(b) for b in r["content"]]}
                    for r in m["results"]]})
            else:
                blocks = []
                for r in m["results"]:
                    blocks += [text(f"Result of {r['name']}:")] + r["content"]
                out.append({"role": "user", "content": [a_block(b) for b in blocks]})
    return out


def a_block(b):
    if b["type"] in ("image", "document"):
        return {"type": b["type"], "source": {"type": "base64", "media_type": b["media_type"], "data": b["data"]}}
    return {"type": "text", "text": b["text"]}


def to_openai(messages, native):
    out = []
    for m in messages:
        if m["role"] == "user":
            out.append({"role": "user", "content": [o_block(b) for b in m["content"]]})
        elif m["role"] == "assistant":
            msg = {"role": "assistant", "content": m.get("text") or ""}
            if native and m["calls"]:
                msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                      "function": {"name": c["name"], "arguments": json.dumps(c["args"])}}
                                     for c in m["calls"]]
            out.append(msg)
        elif m["role"] == "tool":
            images = []
            if native:
                for r in m["results"]:
                    words = "\n".join(b["text"] for b in r["content"] if b["type"] == "text")
                    out.append({"role": "tool", "tool_call_id": r["id"], "content": words})
                    images += [b for b in r["content"] if b["type"] == "image"]
                if images:  # tool messages carry text only, so images follow as a user message
                    out.append({"role": "user", "content": [o_block(text("Images from the tool results:"))] +
                                [o_block(b) for b in images]})
            else:
                blocks = []
                for r in m["results"]:
                    blocks += [text(f"Result of {r['name']}:")] + r["content"]
                out.append({"role": "user", "content": [o_block(b) for b in blocks]})
    return out


def o_block(b):
    if b["type"] == "image":
        return {"type": "image_url", "image_url": {"url": f"data:{b['media_type']};base64,{b['data']}"}}
    return {"type": "text", "text": b["text"]}


# ---------------------------------------------------------------- 4. result
def parse_result(agent, trace, kind, data, native):
    """Text, and tool calls parsed out: what the harness accepts as an instruction."""
    words, calls = "", []
    if kind == "anthropic":
        for b in data.get("content", []):
            if b["type"] == "text":
                words += b["text"]
            elif b["type"] == "tool_use":
                calls.append({"id": b["id"], "name": b["name"], "args": b["input"]})
        u = data.get("usage", {})
        tin, tout = u.get("input_tokens", 0), u.get("output_tokens", 0)
    else:
        msg = data["choices"][0]["message"]
        words = msg.get("content") or ""
        for c in msg.get("tool_calls") or []:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append({"id": c["id"], "name": c["function"]["name"], "args": args})
        u = data.get("usage") or {}
        tin, tout = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
    if not native and agent.path == "goal":
        calls = calls or parse_text_call(words)
    trace.usage(tin, tout)
    trace.log("result", text=words[:2000], calls=calls, tokens_in=tin, tokens_out=tout)
    return {"text": words, "calls": calls}


def text_protocol(tools):
    lines = ["# How to act",
             "You act by calling tools. To call one, reply with a single JSON object and nothing else:",
             '{"tool": "<name>", "args": {...}}',
             "Call one tool per reply. You will get its result, then reply again.",
             "When the task is done, call finish.", "", "Tools:"]
    for n in tools:
        params = ", ".join(f"{k}: {v}" for k, v in TOOLS[n]["args"].items())
        lines.append(f"- {n}({params}): {TOOLS[n]['about']}")
    return "\n".join(lines)


def parse_text_call(words):
    start, end = words.find("{"), words.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        obj = json.loads(words[start:end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(obj, dict) or "tool" not in obj:
        return []
    return [{"id": f"t{int(time.time() * 1000)}", "name": obj["tool"], "args": obj.get("args", {})}]


# ---------------------------------------------------------------- 5. tools
# What the agent can touch. Only tools listed in harness.toml are offered.

def t_list_dir(agent, path="."):
    p = agent.file(path)
    if not p.is_dir():
        return [text(f"{path} is not a folder")]
    names = sorted(f.name + ("/" if f.is_dir() else "") for f in p.iterdir() if not f.name.startswith("."))
    return [text("\n".join(names) or "(empty)")]


def t_read_file(agent, path):
    p = agent.file(path)
    return file_blocks(agent, p) if p.is_file() else [text(f"{path} does not exist")]


def t_write_file(agent, path, content):
    p = agent.file(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return [text(f"wrote {path}")]


def t_append_file(agent, path, content):
    p = agent.file(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(content if content.endswith("\n") else content + "\n")
    return [text(f"appended to {path}")]


def t_move_file(agent, src, dst):
    s, d = agent.file(src), agent.file(dst)
    if not s.is_file():
        return [text(f"{src} does not exist")]
    if dst.endswith("/") or d.is_dir():
        d.mkdir(parents=True, exist_ok=True)
        d = d / s.name
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return [text(f"moved {src} to {d.relative_to(agent.dir)}")]


def t_delete_file(agent, path):
    agent.file(path).unlink()
    return [text(f"deleted {path}")]


def t_ask(agent, question):
    """Ask first. If a person started the run, they answer now; otherwise it waits in a queue."""
    if agent.trigger == "manual":
        say("ask", f"  ? {question}")
        if agent.answers is None:
            answer = input("  your answer › ").strip()
        else:  # an eval: the answer key speaks for the person
            answer = scripted(agent.answers, question)
            say("ask", f"  › {answer} (from golden.jsonl)")
        return [text(f"The person answered: {answer}")]
    q = agent.dir / agent.ask_queue
    q.mkdir(exist_ok=True)
    note = q / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    note.write_text(f"# Waiting for a person\n\n{question}\n")
    say("ask", f"  ? queued for a person: {note.relative_to(agent.dir)}")
    return [text(f"Nobody is here. Your question is queued in {agent.ask_queue}/ for a person. "
                 "Do not take the action; leave the file where it is.")]


def t_notify(agent, message):
    say("notify", f"  ✉ {message}")
    with (agent.dir / "notifications.log").open("a") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')}  {message}\n")
    return [text("sent")]


def t_finish(agent, summary):
    return [text("finished")]


TOOLS = {
    "list_dir": {"fn": t_list_dir, "args": {"path": "folder"}, "about": "List the files in a folder."},
    "read_file": {"fn": t_read_file, "args": {"path": "file"}, "about": "Read a file. Images come back as images."},
    "write_file": {"fn": t_write_file, "args": {"path": "file", "content": "text"}, "about": "Write a text file, replacing it."},
    "append_file": {"fn": t_append_file, "args": {"path": "file", "content": "text"}, "about": "Add a line to the end of a text file."},
    "move_file": {"fn": t_move_file, "args": {"src": "file", "dst": "file or folder/"}, "about": "Move a file, into a folder if dst ends with /."},
    "delete_file": {"fn": t_delete_file, "args": {"path": "file"}, "about": "Delete a file."},
    "ask": {"fn": t_ask, "args": {"question": "text"}, "about": "Ask a person before acting."},
    "notify": {"fn": t_notify, "args": {"message": "text"}, "about": "Send a short message to the person you work for."},
    "finish": {"fn": t_finish, "args": {"summary": "text"}, "about": "Say you are done, with a one line summary."},
}


def schema(name):
    props = {k: {"type": "string", "description": v} for k, v in TOOLS[name]["args"].items()}
    return {"type": "object", "properties": props, "required": list(props)}


def offered_tools(agent):
    return [t for t in agent.tools if t in TOOLS]


# ---------------------------------------------------------------- 6. guardrail
READS = {"list_dir": ["path"], "read_file": ["path"], "move_file": ["src"]}
WRITES = {"write_file": ["path"], "append_file": ["path"], "move_file": ["src", "dst"], "delete_file": ["path"]}


def under(agent, rel, allowed):
    try:
        p = agent.file(rel)
    except PermissionError:
        return False
    for a in allowed:
        base = agent.file(a)
        if p == base or base in p.parents:
            return True
    return False


def guard(agent, name, args):
    """Enforced, whatever the model decides. Returns None to allow, or the reason it is denied."""
    if name not in TOOLS:
        return f"there is no tool called {name}"
    if name not in agent.tools:
        return f"{name} is not one of this agent's tools"
    if name in agent.deny:
        return f"{name} is denied by the harness"
    missing = [k for k in TOOLS[name]["args"] if k not in args]
    if missing:
        return f"missing arguments: {', '.join(missing)}"
    for k in READS.get(name, []):
        if not under(agent, args[k], agent.read + agent.write):
            return f"{args[k]} is not readable"
    for k in WRITES.get(name, []):
        if not under(agent, args[k], agent.write):
            return f"{args[k]} is not writable"
    return None


def run_tool(agent, trace, call):
    name, args = call["name"], call["args"]
    shown = ", ".join(f"{v}" for v in args.values())[:120]
    reason = guard(agent, name, args)
    if reason:
        say("denied", f"  ✗ {name}({shown}) DENIED: {reason}")
        trace.log("denied", tool=name, args=args, reason=reason)
        return [text(f"DENIED by the harness: {reason}")]
    say("tool", f"  · {name}({shown})")
    try:
        out = TOOLS[name]["fn"](agent, **{k: str(args[k]) for k in TOOLS[name]["args"]})
    except Exception as e:  # a failed tool is a result the model can see
        out = [text(f"error: {e}")]
    trace.log("tool", tool=name, args=args, result=[b.get("text", f"[{b['type']}]") for b in out])
    return out


# ---------------------------------------------------------------- 7. the loop
def run_goal(agent, first_message, label):
    """Open path: the model picks each next step until it finishes or the budget ends."""
    say("run", f"▶ {agent.name} · goal · {label}")
    trace = Trace(agent, label)
    system, messages = assemble_context(agent, trace, [text(first_message)])
    tools = offered_tools(agent)
    for turn in range(1, agent.max_turns + 1):
        if time.time() - trace.start > agent.max_seconds:
            return trace.close(f"stopped by the harness: over {agent.max_seconds}s")
        result = call_model(agent, trace, system, messages, tools)
        if result["text"].strip() and (tool_mode(agent) == "native" or not result["calls"]):
            say("info", "  " + result["text"].strip().replace("\n", "\n  ")[:800])
        messages.append({"role": "assistant", "text": result["text"], "calls": result["calls"]})
        if not result["calls"]:
            return trace.close("done: the model stopped calling tools")
        results = []
        for call in result["calls"]:  # feedback: every result goes back into the context
            results.append({"id": call["id"], "name": call["name"], "content": run_tool(agent, trace, call)})
            if call["name"] == "finish" and guard(agent, "finish", call["args"]) is None:
                say("info", f"  {call['args'].get('summary', '')}")
                return trace.close("done: the model called finish")
        messages.append({"role": "tool", "results": results})
    return trace.close(f"stopped by the harness: {agent.max_turns} turns")


def run_steps(agent, items, label, fresh):
    """Fixed path: code picks every step. The model does the work inside one step: one call per file."""
    say("run", f"▶ {agent.name} · steps · {label} · {len(items)} file(s)")
    trace = Trace(agent, label)
    out = agent.file(agent.cfg["output"])
    if fresh or not out.exists():
        out.write_text(agent.cfg.get("header", "") + "\n" if agent.cfg.get("header") else "")
    for p in items:  # step 1: take the next file
        rel = p.relative_to(agent.dir)
        system, messages = assemble_context(agent, trace, [text(f"File: {rel}")] + file_blocks(agent, p))
        result = call_model(agent, trace, system, messages, None)  # step 2: one model call, no tools
        if agent.cfg.get("output_lines", "first") == "all":  # the whole answer, under the file's name
            row = f"{p.name}\n{result['text'].strip()}\n"
        else:  # first: one CSV row, the file's name and the answer's first line
            line = next((l.strip() for l in result["text"].splitlines() if l.strip() and not l.startswith("```")), "")
            buf = io.StringIO()
            csv.writer(buf).writerow([p.name])
            row = buf.getvalue().strip() + "," + line
        with out.open("a") as f:  # step 3: code writes the row
            f.write(row + "\n")
        say("tool", f"  · row: {row}")
        trace.log("step", file=str(rel), row=row)
    trace.close("done: the steps ended")


# ---------------------------------------------------------------- triggers
def countdown(seconds):
    """Wait for the next tick, showing the seconds left on one line, rewritten in place."""
    if not sys.stdout.isatty():  # piped or logged: no line per second
        return time.sleep(seconds)
    for left in range(round(seconds), 0, -1):
        line = f"  next check in {left}s"
        print(f"\r\033[2m{line}\033[0m\033[K" if styled() else f"\r{line}\033[K", end="", flush=True)
        time.sleep(1)
    print("\r\033[K", end="", flush=True)  # clear it before the next check prints


def inbox_files(agent):
    folder = agent.file(agent.cfg.get("input", "inbox"))
    folder.mkdir(exist_ok=True)
    return sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))


def run(agent, message=None):
    """What begins each run: you, a timer, or a new file."""
    if agent.cfg.get("fresh", True):  # a timer or watcher starts clean once, so memory carries across its runs
        reset(agent)
    if agent.trigger == "manual":
        if agent.path == "steps":
            return run_steps(agent, inbox_files(agent), "manual", fresh=True)
        return run_goal(agent, message or agent.cfg.get("start", "Do the task in your spec."), "manual")

    first = len(summary_rows(agent.dir)[0])  # this session's runs are the ones after these
    every = agent.cfg.get("every", 30)
    done_log = agent.dir / ".processed"
    seen = set(done_log.read_text().splitlines()) if done_log.exists() else set()
    if agent.trigger == "on_new_file":
        seen |= {p.name for p in inbox_files(agent)}  # files already here do not start a run
        every = agent.cfg.get("poll", 2)
    say("run", f"● {agent.name} is {'watching ' + agent.cfg.get('input', 'inbox') + '/' if agent.trigger == 'on_new_file' else f'running every {every}s'}. Ctrl-C to stop.")
    tick = 0
    try:
        while True:
            tick += 1
            new = [p for p in inbox_files(agent) if p.name not in seen]
            if agent.trigger == "on_new_file":
                for p in new:
                    time.sleep(0.5)  # let the copy finish
                    rel = p.relative_to(agent.dir)
                    run_goal(agent, f"A new file arrived: {rel}", p.stem)
                    seen.add(p.name)
            else:
                if new:
                    if agent.path == "steps":
                        run_steps(agent, new, f"tick{tick}", fresh=False)
                    else:
                        run_goal(agent, f"Scheduled run. New files: {', '.join(p.name for p in new)}", f"tick{tick}")
                    seen |= {p.name for p in new}
                    done_log.write_text("\n".join(sorted(seen)) + "\n")  # bookkeeping, not judgment
                else:
                    say("tick", f"  tick {tick} · {datetime.now():%H:%M:%S} · no new files")
            countdown(every) if agent.trigger == "every" else time.sleep(every)
    except KeyboardInterrupt:
        say("info", "\nstopped")
        for trace in list(OPEN_TRACES):  # the run Ctrl-C cut short still counts
            trace.close("stopped before the end")
        runs, calls, tokens_in, tokens_out, seconds, dollars = totals(summary_rows(agent.dir)[0][first:])
        say("done", f"■ this session: {runs} run(s) · {calls} model calls · {tokens_in:,} tokens in · "
                    f"{tokens_out:,} out · {seconds}s · {money(dollars)}")


# ---------------------------------------------------------------- 9. graders
# Each grader reads one finished run folder and checks one case from golden.jsonl: True or False.
# The cases are data, so these five check any job. Nothing here knows what the agent was for.

def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def tables(p):
    """Every table in a markdown or CSV file, as (header, rows), each row a list of cells."""
    if not p.is_file():
        return []
    if p.suffix.lower() == ".csv":
        rows = [r for r in csv.reader(io.StringIO(p.read_text(errors="replace"))) if any(c.strip() for c in r)]
        return [(rows[0], rows[1:])] if rows else []
    lines, found, i = p.read_text(errors="replace").splitlines(), [], 0
    while i < len(lines) - 1:
        rule = cells(lines[i + 1])
        if lines[i].strip().startswith("|") and all(re.fullmatch(r":?-+:?", c) for c in rule):
            header, rows, i = cells(lines[i]), [], i + 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            found.append((header, rows))
        else:
            i += 1
    return found


def find_row(p, key):
    """The row that names key. Of the rows with a cell containing it, the one where that cell is
    shortest: 'cafe_luna_0914.jpg' finds its own row, not a row that mentions it. Never by position."""
    best = None
    for header, rows in tables(p):
        for row in rows:
            hits = [len(c) for c in row if key.lower() in c.lower()]
            if hits and (best is None or min(hits) < best[0]):
                best = (min(hits), header, row)
    return (best[1], best[2]) if best else (None, None)


def numbers(s):
    """'$412.02', '412.02', '7,60 €', '1,234.50': every number in s. A comma before one or two final digits is a decimal comma."""
    out = []
    for n in re.findall(r"\d[\d.,]*\d|\d", s):
        if "," in n and "." in n:
            n = n.replace(".", "").replace(",", ".") if n.rfind(",") > n.rfind(".") else n.replace(",", "")
        elif "," in n:
            n = n.replace(",", ".") if n.count(",") == 1 and re.search(r",\d{1,2}$", n) else n.replace(",", "")
        elif n.count(".") > 1:
            n = n.replace(".", "")
        try:
            out.append(float(n))
        except ValueError:
            pass
    return out


def has_any(s, words):
    return any(str(w).lower() in s.lower() for w in words)


def g_text_contains(folder, case):
    p = folder / case["file"]
    return p.is_file() and has_any(p.read_text(errors="replace"), case["any"])


def g_text_lacks(folder, case):
    p = folder / case["file"]
    return p.is_file() and not has_any(p.read_text(errors="replace"), case["any"])


def g_row_value(folder, case):
    header, row = find_row(folder / case["file"], case["row"])
    if row is None:
        return False
    if "column" in case:
        col = next((i for i, h in enumerate(header) if case["column"].lower() in h.lower()), None)
        if col is None or col >= len(row):
            return False
        cell = row[col]
    else:  # no column: the whole row
        cell = " | ".join(row)
    if "near" in case and any(abs(n - case["near"]) <= 0.01 for n in numbers(cell)):
        return True
    return has_any(cell, case.get("any", []))


def g_file_in(folder, case):
    return (folder / case["path"]).exists()


def tool_calls(folder):
    """Every tool call in the run's traces, allowed ("tool") or denied, in order."""
    out = []
    for t in sorted((folder / "traces").glob("*.jsonl")):
        if t.name == "summary.jsonl":
            continue
        for line in t.read_text().splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(e, dict) and e.get("event") in ("tool", "denied"):
                out.append(e)
    return out


def call_matches(e, want):
    """Same tool, and args_contain in its paths (or in all its args, for a tool without paths)."""
    names = want["tool"] if isinstance(want["tool"], list) else [want["tool"]]
    args = e.get("args") if isinstance(e.get("args"), dict) else {}
    if e.get("tool") not in names:
        return False
    keys = READS.get(e["tool"], []) + WRITES.get(e["tool"], []) or list(args)  # a report's text is not a path
    return str(want.get("args_contain", "")).lower() in " ".join(str(args.get(k, "")) for k in keys).lower()


def g_tool_call(folder, case):
    calls = tool_calls(folder)
    if case.get("never"):  # allowed or denied: trying counts
        return not any(call_matches(e, case) for e in calls)
    done = [e for e in calls if e["event"] == "tool"]
    first = next((i for i, e in enumerate(done) if call_matches(e, case)), None)
    if first is None or "before" not in case:
        return first is not None
    later = next((i for i, e in enumerate(done) if call_matches(e, case["before"])), None)
    return later is not None and first < later


GRADERS = {"text_contains": g_text_contains, "text_lacks": g_text_lacks, "row_value": g_row_value,
           "file_in": g_file_in, "tool_call": g_tool_call}


def wilson(k, n, z=1.96):
    """The 95% interval for a pass rate, in percent. Honest at small n, where k/n alone is not."""
    if n == 0:
        return 0, 100
    p = k / n
    mid, spread = p + z * z / (2 * n), z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round(100 * (mid - spread) / (1 + z * z / n)), round(100 * (mid + spread) / (1 + z * z / n))


# ---------------------------------------------------------------- answer key and eval
def latest_trace(agent):
    traces = sorted(p for p in (agent.dir / "traces").glob("*.jsonl") if p.name != "summary.jsonl")
    return traces[-1] if traces else None


def start_inbox(agent):
    """The file names in the inbox when a run starts: eval_inbox if harness.toml lists it, else
    what is there now plus what reset seeds."""
    if "eval_inbox" in agent.cfg:
        return list(agent.cfg["eval_inbox"])
    names = {p.name for p in inbox_files(agent)}
    if agent.cfg.get("seed", False):
        names |= {p.name for p in RECEIPTS.iterdir() if p.is_file()}
    return sorted(names)


def run_outputs(agent):
    """Every file the run left: anything in the folder but its own files, traces, evals and the inbox."""
    inbox = agent.file(agent.cfg.get("input", "inbox"))
    out = []
    for p in sorted(agent.dir.rglob("*")):
        rel = p.relative_to(agent.dir)
        if p.is_file() and rel.parts[0] not in KEEP and inbox not in p.parents \
                and not any(part.startswith(".") for part in rel.parts):
            out.append(p)
    return out


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def is_number(cell):
    bare = re.sub(r"[$€£¥*`\s]|usd|eur|gbp", "", cell.lower())
    return bool(re.fullmatch(r"[-+]?[\d.,]*\d[\d.,]*", bare))


def draft_golden(agent, force=False):
    """A first answer key, drafted from the latest run. It holds what the model did, not what is right."""
    golden = agent.dir / "golden.jsonl"
    if golden.exists() and not force:
        raise SystemExit(f"{golden.relative_to(ROOT)} exists: correct it by hand, or add --force to draft over it")
    trace = latest_trace(agent)
    if trace is None:
        say("run", "no run yet, running once to draft from")
        try:
            run(agent)
        finally:
            for t in list(OPEN_TRACES):
                t.close("stopped before the end")
        trace = latest_trace(agent)
    note = f"drafted from run {trace.name}, verify by hand"
    cases = []

    def add(name, grader, **fields):
        cid, n = slug(name), 2
        while cid in {c["id"] for c in cases}:
            cid, n = f"{slug(name)}-{n}", n + 1
        cases.append({"id": cid, "grader": grader, "settled": None, "note": note, **fields})

    outputs = run_outputs(agent)
    texts = [p for p in outputs if p.suffix.lower() in TEXT_TYPES]
    for p in outputs:  # a file the run made or moved that is not text: check that it is there
        if p not in texts:
            add(f"{p.name} in {p.parent.name}", "file_in", path=str(p.relative_to(agent.dir)))
    for name in start_inbox(agent):
        for p in texts:
            rel = str(p.relative_to(agent.dir))
            header, row = find_row(p, name)
            if row is None:
                add(f"{Path(name).stem} mentioned", "text_contains", file=rel, any=[name])
                continue
            for column, cell in zip(header, row):
                if not cell or name.lower() in cell.lower():
                    continue
                if is_number(cell):
                    add(f"{Path(name).stem} {column}", "row_value", file=rel, row=name, column=column, near=numbers(cell)[0])
                else:
                    add(f"{Path(name).stem} {column}", "row_value", file=rel, row=name, column=column, any=[cell])
    writers = [t for t in agent.tools if t in WRITES]
    for folder in [f for f in agent.read if f not in agent.write]:
        if writers:
            inside = folder if Path(folder).suffix else folder.rstrip("/") + "/"
            add(f"never writes {folder}", "tool_call", tool=writers, args_contain=inside, never=True)
    answers = []
    for line in trace.read_text().splitlines():  # every question the model asked gets a blank answer
        e = json.loads(line)
        if e.get("event") == "tool" and e.get("tool") == "ask":
            words = re.findall(r"[A-Za-z]+", str(e["args"].get("question", "")))
            if words and max(words, key=len).lower() not in [a["match"].lower() for a in answers]:
                answers.append({"match": max(words, key=len), "answer": ""})
    with golden.open("w") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
        f.write(json.dumps({"answers": answers}, ensure_ascii=False) + "\n")
    say("done", f"drafted {len(cases)} case(s) and {len(answers)} answer(s) in {golden.relative_to(ROOT)}")
    say("info", f"  from the run in {trace.relative_to(ROOT)}")
    say("info", "  This draft holds the model's answers, not a verified key. Correct every case, then set its\n"
                "  settled to true (checked, it must pass) or false (checked, the answer is still open),\n"
                "  and fill in each answer the agent will get when it asks.")


def load_golden(agent):
    p = agent.dir / "golden.jsonl"
    if not p.exists():
        raise SystemExit(f"no golden.jsonl in {agent.dir.relative_to(ROOT)}: run python3 mva.py golden "
                         f"{agent.dir.relative_to(ROOT)} first")
    cases, answers = [], []
    for n, line in enumerate(p.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise SystemExit(f"golden.jsonl line {n} is not JSON: {e}")
        if isinstance(obj, dict) and "answers" in obj and "grader" not in obj:
            answers += obj["answers"]
        elif not isinstance(obj, dict) or "id" not in obj or obj.get("grader") not in GRADERS:
            raise SystemExit(f"golden.jsonl line {n}: a case needs an id and a grader: {', '.join(GRADERS)}")
        else:
            cases.append(obj)
    return cases, answers


def scripted(answers, question):
    """The first answer whose match is in the question, ignoring case. "No." when none is."""
    for a in answers:
        if a.get("answer") and str(a.get("match", "")).lower() in question.lower():
            return a["answer"]
    return "No."


def eval_copy(agent, folder):
    """A fresh copy of the setup for one run, seeded the way reset does, or from eval_inbox if harness.toml lists one."""
    if agent.cfg.get("fresh", True):
        folder.mkdir(parents=True)
        for name in ("spec.md", "harness.toml"):
            shutil.copy(agent.dir / name, folder / name)
    else:  # no reset before a run: it starts from the folder as it is
        shutil.copytree(agent.dir, folder, ignore=lambda d, names: [n for n in names if Path(d) == agent.dir
                                                                    and n in KEEP - {"spec.md", "harness.toml"}])
    inbox = folder / agent.cfg.get("input", "inbox")
    if "eval_inbox" in agent.cfg:
        shutil.rmtree(inbox, ignore_errors=True)
        inbox.mkdir(parents=True)
        for name in agent.cfg["eval_inbox"]:
            places = (agent.file(agent.cfg.get("input", "inbox")), RECEIPTS, RECEIPTS / "extras")
            src = next((d / name for d in places if (d / name).is_file()), None)
            if src is None:
                raise SystemExit(f"eval_inbox lists {name}, which is not in {agent.cfg.get('input', 'inbox')}/ or receipts/")
            shutil.copy(src, inbox / name)
    else:
        inbox.mkdir(parents=True, exist_ok=True)
        if agent.cfg.get("fresh", True) and agent.cfg.get("seed", False):
            for p in RECEIPTS.iterdir():
                if p.is_file():
                    shutil.copy(p, inbox / p.name)


def eval_once(n, folder, answers):
    """One run in its own folder, started the way its trigger would start it, with nobody at the keyboard."""
    LOCAL.prefix = f"[run-{n}] "
    agent = Agent(folder)
    agent.answers = answers
    try:
        if agent.path == "steps":
            run_steps(agent, inbox_files(agent), "eval", fresh=True)
        elif agent.trigger == "on_new_file":  # each file arrives on its own
            for p in inbox_files(agent):
                run_goal(agent, f"A new file arrived: {p.relative_to(agent.dir)}", p.stem)
        elif agent.trigger == "every":
            run_goal(agent, f"Scheduled run. New files: {', '.join(p.name for p in inbox_files(agent))}", "eval")
        else:
            run_goal(agent, agent.cfg.get("start", "Do the task in your spec."), "eval")
    except (Exception, SystemExit) as e:  # a failed run is a result, not the end of the eval
        say("failed", f"✗ {e}")
    finally:
        for trace in [t for t in OPEN_TRACES if t.agent is agent]:
            trace.close("stopped before the end")
    rows = summary_rows(folder)[0]
    _, _, tokens_in, tokens_out, seconds, dollars = totals(rows)
    failed = [r.get("outcome", "") for r in rows if mark(r.get("outcome", "")) == "✗"]
    outcome = failed[0] if failed else rows[-1].get("outcome", "") if rows else "no run"
    return {"run": n, "model": agent.model, "outcome": outcome, "tokens": tokens_in + tokens_out,
            "seconds": seconds, "cost": dollars}


def run_eval(agent, runs=20, jobs=4, allow_unverified=False):
    """Run the setup many times, each in its own copy, and grade every run against golden.jsonl."""
    cases, answers = load_golden(agent)
    unverified = [c["id"] for c in cases if c.get("settled") is None]
    if unverified and not allow_unverified:
        raise SystemExit(f"{len(unverified)} case(s) in golden.jsonl are not verified yet: {', '.join(unverified)}\n"
                         "Check each one and set settled to true or false, or add --allow-unverified.")
    base = agent.dir / "evals" / datetime.now().strftime("%Y%m%d-%H%M%S")
    folders = [base / f"run-{n}" for n in range(1, runs + 1)]
    for folder in folders:
        eval_copy(agent, folder)
    say("run", f"▶ eval {agent.name} · {len(cases)} case(s) · {runs} run(s), {jobs} at a time · {agent.model}")
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(eval_once, range(1, runs + 1), folders, [answers] * runs))
    for r, folder in zip(results, folders):  # a run that did not end as planned fails every case
        r["cases"] = {c["id"]: mark(r["outcome"]) == "✓" and GRADERS[c["grader"]](folder, c) for c in cases}
    with (base / "results.jsonl").open("w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    report = eval_summary(agent, cases, results, folders)
    (base / "summary.md").write_text(report)
    print()
    print(report)
    say("done", f"■ saved: {(base / 'summary.md').relative_to(ROOT)}")


def eval_summary(agent, cases, results, folders):
    """The eval as a short report: what holds, what fails and in which runs, what is undecided, and what to do next."""
    runs = len(results)
    _, _, tokens_in, tokens_out, seconds, dollars = totals([row for f in folders for row in summary_rows(f)[0]])
    passes = {c["id"]: sum(r["cases"][c["id"]] for r in results) for c in cases}

    def line(c):
        k, failed = passes[c["id"]], [f"run-{r['run']}" for r in results if not r["cases"][c["id"]]]
        where = f", failed in {', '.join(failed[:5])}{' and more' if len(failed) > 5 else ''}" if 0 < k < runs else ""
        return f"- {c['id']}: {k}/{runs} ({round(100 * k / runs)}%){where}. {c.get('note', '')}"

    checked = [c for c in cases if c.get("settled") is True]
    groups = [
        ("✓ Holds in every run", [c for c in checked if passes[c["id"]] == runs],
         f"{runs} runs can still miss a failure that happens up to {100 - wilson(runs, runs)[0]}% of the time. "
         "Run more before you rely on these."),
        ("✗ Fails in some runs", [c for c in checked if 0 < passes[c["id"]] < runs],
         "Open a failed run's folder and read its output and trace. If the agent was wrong, change spec.md. "
         "If the agent was right and the case is too strict, change golden.jsonl."),
        ("✗ Fails in every run", [c for c in checked if passes[c["id"]] == 0],
         "Check one run to make sure the case is right, then change spec.md or harness.toml."),
        ("○ Not decided yet: the agent decided for you", [c for c in cases if c.get("settled") is False],
         "These cases are settled: false in golden.jsonl, so there is no right answer yet. The rate shows what the "
         "agent chooses. Decide the answer, write it into spec.md, set settled to true, and run the eval again."),
        ("? Not checked yet", [c for c in cases if c.get("settled") is None],
         "Still drafts. Check each against the files and set settled to true or false."),
    ]
    out = [f"# Eval: {agent.name}", "",
           f"{runs} runs of {agent.model} · {tokens_in + tokens_out:,} tokens · {money(dollars)} · "
           f"{seconds / runs:.1f}s per run", ""]
    stopped = [r for r in results if mark(r["outcome"]) == "✗"]
    if stopped:
        out += [f"## ✗ Stopped before the end ({len(stopped)} of {runs})", ""]
        out += [f"- run-{r['run']}: {r['outcome']}" for r in stopped]
        out += ["", "These runs fail every case below. Their traces/ show where they stopped.", ""]
    for title, group, advice in groups:
        if group:
            out += [f"## {title} ({len(group)})", ""] + [line(c) for c in group] + ["", advice, ""]
    out += ["## Next", "", "Change one thing, spec.md or the model, run the eval again, and compare its summary.md "
            "with this one. Each run's files are in its own run-<n>/ folder."]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- commands
KEEP = {"spec.md", "harness.toml", "traces", "golden.jsonl", "evals"}  # the answer key and eval results outlive a reset


def reset(agent):
    """Back to a clean folder: delete outputs and memory.md, refill the inbox if seed = true.
    Trace files stay; a new session starts, so usage counts only the runs after this."""
    for p in agent.dir.iterdir():
        if p.name in KEEP:
            continue
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    inbox = agent.file(agent.cfg.get("input", "inbox"))
    inbox.mkdir(exist_ok=True)
    if agent.cfg.get("seed", False):
        for p in RECEIPTS.iterdir():
            if p.is_file():
                shutil.copy(p, inbox / p.name)
    (agent.dir / "traces" / "summary.jsonl").unlink(missing_ok=True)
    say("done", f"reset {agent.name}: {len(list(inbox.iterdir()))} file(s) in {inbox.relative_to(agent.dir)}/")


PRICES = {  # USD per million tokens (input, output), September 2026: add a line for your model
    "anthropic/claude-opus-5-5": (4.00, 20.00),
    "anthropic/claude-opus-5": (5.00, 25.00),
    "anthropic/claude-sonnet-5-5": (2.00, 10.00),
    "anthropic/claude-sonnet-5": (2.00, 10.00),
    "anthropic/claude-haiku-4-5": (1.00, 5.00),
    "openrouter/z-ai/glm-5.3-flash": (0.15, 0.50),
}


def cost(model, tokens_in, tokens_out):
    """Dollars for one run, or None when the model's price is not in PRICES. Local models are free."""
    if model.startswith("ollama/") or model.endswith(":free") or model == "openrouter/openrouter/free":
        return 0.0
    if model not in PRICES:
        return None
    price_in, price_out = PRICES[model]
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


def mark(outcome):
    """✓ when a run ended as planned, ✗ when the harness, an error or Ctrl-C stopped it."""
    return "✓" if str(outcome).startswith("done") else "✗"


def money(dollars):
    return "?" if dollars is None else f"${dollars:.4f}"


def num(row, key):
    value = row.get(key, 0)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def totals(rows):
    """runs, model calls, tokens in, tokens out, seconds, dollars (None if any price is unknown)."""
    costs = [cost(str(r.get("model", "")), num(r, "tokens_in"), num(r, "tokens_out")) for r in rows]
    return (len(rows), sum(num(r, "model_calls") for r in rows), sum(num(r, "tokens_in") for r in rows),
            sum(num(r, "tokens_out") for r in rows), round(sum(num(r, "seconds") for r in rows), 1),
            None if None in costs else sum(costs))


def summary_rows(folder):
    """One dict per run since the last reset. A broken line is counted and skipped, not a crash."""
    s = Path(folder) / "traces" / "summary.jsonl"
    rows, broken = [], 0
    if s.exists():
        for line in s.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                row = None
            if isinstance(row, dict) and isinstance(row.get("model"), str):
                rows.append(row)
            else:  # not JSON, or not a run
                broken += 1
    return rows, broken


def show_usage(folders, per_run=False):
    """Tokens, time and cost for each setup since its last reset; per_run lists every run."""
    print(f"{'setup':<20}{'path':<7}{'trigger':<13}{'model':<28}{'runs':>5}{'ok':>5}{'calls':>7}{'tokens in':>11}"
          f"{'out':>8}{'seconds':>9}{'cost':>10}")
    for folder in folders:
        rows, broken = summary_rows(folder)
        if not rows:
            continue
        runs, calls, tokens_in, tokens_out, seconds, dollars = totals(rows)
        failed = sum(mark(r.get("outcome", "")) == "✗" for r in rows)
        ok = "✓" if not failed else f"✗{failed}"
        last = rows[-1]
        print(f"{str(last.get('agent', Path(folder).name)):<20}{str(last.get('path', '?')):<7}"
              f"{str(last.get('trigger', '?')):<13}{str(last.get('model', '?'))[:27]:<28}{runs:>5}{ok:>5}"
              f"{calls:>7}{tokens_in:>11,}{tokens_out:>8,}{seconds:>9}{money(dollars):>10}")
        if per_run:
            for r in rows:
                dollars = cost(str(r.get("model", "")), num(r, "tokens_in"), num(r, "tokens_out"))
                when = str(r.get("time", ""))[11:19]
                print(f"  {when:<18}{str(r.get('label', ''))[:47]:<48}{'':>5}{mark(r.get('outcome', '')):>5}"
                      f"{num(r, 'model_calls'):>7}"
                      f"{num(r, 'tokens_in'):>11,}{num(r, 'tokens_out'):>8,}{num(r, 'seconds'):>9}"
                      f"{money(dollars):>10}  {r.get('outcome', '')}")
        if broken:
            print(f"  ({broken} broken line(s) in {folder}/traces/summary.jsonl skipped)")


def option(argv, name, default=None):
    """The value after --name, as in --runs 20."""
    return argv[argv.index(name) + 1] if name in argv[:-1] else default


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return
    cmd = argv[1]
    if cmd == "usage":
        per_run = "--runs" in argv[2:]
        folders = [a for a in argv[2:] if a != "--runs"]
        folders = folders or sorted(str(p) for p in (ROOT / "setups").iterdir() if p.is_dir())
        return show_usage(folders, per_run)
    if cmd == "eval" and option(argv, "--model"):
        os.environ["MVA_MODEL"] = option(argv, "--model")  # this eval only: it ends with the process
    agent = Agent(argv[2])
    if cmd == "golden":
        draft_golden(agent, force="--force" in argv[3:])
    elif cmd == "eval":
        run_eval(agent, runs=int(option(argv, "--runs", 20)), jobs=int(option(argv, "--jobs", 4)),
                 allow_unverified="--allow-unverified" in argv[3:])
    elif cmd == "run":
        try:
            run(agent, " ".join(argv[3:]) or None)
        finally:  # a run cut short by an error or Ctrl-C still reaches usage, with what it spent
            for trace in list(OPEN_TRACES):
                trace.close("stopped before the end")
    elif cmd == "reset":
        reset(agent)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
