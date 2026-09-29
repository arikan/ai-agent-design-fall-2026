#!/usr/bin/env python3
"""
mva: a minimum viable agent harness.

One file, standard library only (Python 3.11+). Each section below is one box
of the agent architecture: context, router, model call, result, tool,
guardrail, the loop, and the trace. Triggers decide what begins each run.

An agent is a folder with two files:
  spec.md       what the model reads (requested)
  harness.toml  what this program enforces (enforced)

Two settings in harness.toml place the agent on the Autonomy Grid:
  path    = "steps" | "goal"                 who picks the next step
  trigger = "manual" | "every" | "on_new_file"   what begins each run

Usage:
  python mva.py run   agents/task
  python mva.py reset agents/task
  python mva.py drop  agents/standing receipts/extras/cafe_luna_0921.jpg
  python mva.py board
"""
import base64
import csv
import io
import json
import os
import shutil
import sys
import time
import tomllib
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RECEIPTS = ROOT / "receipts"
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
TEXT_TYPES = {".txt", ".md", ".csv", ".log", ".json", ".toml"}


# ---------------------------------------------------------------- terminal
def say(kind, text):
    colors = {"model": "2", "tool": "36", "denied": "31;1", "ask": "33;1", "notify": "35;1",
              "done": "32;1", "info": "0", "tick": "2", "run": "1"}
    print(f"\033[{colors.get(kind, '0')}m{text}\033[0m", flush=True)


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
        self.model = c.get("model", "anthropic/claude-sonnet-5")
        self.tools = c.get("tools", [])
        self.deny = c.get("deny", [])
        self.read = c.get("read", [])
        self.write = c.get("write", [])
        self.memory = c.get("memory")
        self.ask_queue = c.get("ask_queue", "pending")
        self.max_turns = c.get("max_turns", 30)
        self.max_seconds = c.get("max_seconds", 300)

    def file(self, rel):
        """Resolve a path the model gives us. It must stay inside the agent folder."""
        p = (self.dir / rel).resolve()
        if self.dir not in p.parents and p != self.dir:
            raise PermissionError(f"{rel} is outside the agent folder")
        return p


# ---------------------------------------------------------------- 8. trace
class Trace:
    """Every run leaves a file: traces/<time>.jsonl. Evaluation reads these."""

    def __init__(self, agent, label):
        self.agent = agent
        (agent.dir / "traces").mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = agent.dir / "traces" / f"{stamp}-{label}.jsonl"
        self.start = time.time()
        self.tokens_in = self.tokens_out = self.calls = 0

    def log(self, event, **data):
        with self.path.open("a") as f:
            f.write(json.dumps({"t": round(time.time() - self.start, 2), "event": event, **data}) + "\n")

    def usage(self, tin, tout):
        self.calls += 1
        self.tokens_in += tin
        self.tokens_out += tout

    def close(self, outcome):
        secs = round(time.time() - self.start, 1)
        summary = {"agent": self.agent.name, "path": self.agent.path, "trigger": self.agent.trigger,
                   "model": self.agent.model, "model_calls": self.calls, "tokens_in": self.tokens_in,
                   "tokens_out": self.tokens_out, "seconds": secs, "outcome": outcome,
                   "time": datetime.now().isoformat(timespec="seconds")}
        self.log("end", **summary)
        with (self.agent.dir / "traces" / "summary.jsonl").open("a") as f:
            f.write(json.dumps(summary) + "\n")
        say("done", f"■ {outcome} · {self.calls} model calls · {self.tokens_in:,} tokens in · "
                    f"{self.tokens_out:,} out · {secs}s · trace: {self.path.relative_to(ROOT)}")


# ---------------------------------------------------------------- content blocks
# Inside the harness, content is a list of blocks: {"type": "text", "text": ...}
# or {"type": "image", "media_type": ..., "data": <base64>}. Each backend converts.

def text(s):
    return {"type": "text", "text": s}


def file_blocks(p):
    ext = p.suffix.lower()
    if ext in IMAGE_TYPES:
        return [text(f"[image: {p.name}]"),
                {"type": "image", "media_type": IMAGE_TYPES[ext], "data": base64.b64encode(p.read_bytes()).decode()}]
    if ext in TEXT_TYPES:
        return [text(p.read_text()[:20000])]
    return [text(f"{p.name}: this harness cannot read {ext} files.")]


# ---------------------------------------------------------------- 1. context
def assemble_context(agent, trace, first_message):
    """Everything the model reads: its instructions, the spec, memory, tool descriptions."""
    parts = [agent.spec]
    if agent.memory:
        mem = agent.file(agent.memory)
        notes = mem.read_text() if mem.exists() else "(empty)"
        parts.append(f"# Your memory ({agent.memory}), written by your earlier runs\n\n{notes}")
    tools = offered_tools(agent)
    if agent.path == "goal" and tool_mode(agent) == "text":
        parts.append(text_protocol(tools))
    system = "\n\n".join(parts)
    trace.log("context", spec_chars=len(agent.spec), memory_chars=len(parts[1]) if agent.memory else 0,
              tools=[t for t in tools], system_chars=len(system))
    return system, [{"role": "user", "content": first_message}]


# ---------------------------------------------------------------- 2. router
def route(model):
    """'anthropic/claude-sonnet-5' · 'ollama/gemma3' · 'openrouter/<vendor>/<model>'"""
    provider, _, name = model.partition("/")
    if provider == "anthropic":
        return "anthropic", name, "https://api.anthropic.com/v1/messages"
    if provider == "ollama":
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        return "openai", name, host.rstrip("/") + "/v1/chat/completions"
    if provider == "openrouter":
        return "openai", name, "https://openrouter.ai/api/v1/chat/completions"
    raise ValueError(f"unknown provider in model '{model}': use anthropic/, ollama/ or openrouter/")


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
        headers = {"x-api-key": need_key("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"}
    else:
        body = {"model": name, "messages": [{"role": "system", "content": system}] + to_openai(messages, native)}
        if native:
            body["tools"] = [{"type": "function", "function": {"name": n, "description": TOOLS[n]["about"],
                                                               "parameters": schema(n)}} for n in tools]
        headers = {}
        if "openrouter.ai" in url:
            headers["Authorization"] = "Bearer " + need_key("OPENROUTER_API_KEY")
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
    if b["type"] == "image":
        return {"type": "image", "source": {"type": "base64", "media_type": b["media_type"], "data": b["data"]}}
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
    return file_blocks(p) if p.is_file() else [text(f"{path} does not exist")]


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
        answer = input("  your answer › ").strip()
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
    trace.log("tool", tool=name, args=args, result=[b.get("text", "[image]") for b in out])
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
        system, messages = assemble_context(agent, trace, [text(f"File: {rel}")] + file_blocks(p))
        result = call_model(agent, trace, system, messages, None)  # step 2: one model call, no tools
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
def inbox_files(agent):
    folder = agent.file(agent.cfg.get("input", "inbox"))
    folder.mkdir(exist_ok=True)
    return sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))


def run(agent, message=None):
    """What begins each run: you, a timer, or a new file."""
    if agent.trigger == "manual":
        if agent.path == "steps":
            return run_steps(agent, inbox_files(agent), "manual", fresh=True)
        return run_goal(agent, message or agent.cfg.get("start", "Do the task in your spec."), "manual")

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
            time.sleep(every)
    except KeyboardInterrupt:
        say("info", "\nstopped")


# ---------------------------------------------------------------- commands
KEEP = {"spec.md", "harness.toml", "policy.md", "memory.start.md"}


def reset(agent):
    """Back to a clean folder: delete outputs, refill the inbox if seed = true, restart memory."""
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
    if agent.memory and (agent.dir / "memory.start.md").exists():
        shutil.copy(agent.dir / "memory.start.md", agent.file(agent.memory))
    say("done", f"reset {agent.name}: {len(list(inbox.iterdir()))} file(s) in {inbox.relative_to(agent.dir)}/")


def drop(agent, files):
    inbox = agent.file(agent.cfg.get("input", "inbox"))
    inbox.mkdir(exist_ok=True)
    for f in files:
        shutil.copy(f, inbox / Path(f).name)
        say("info", f"dropped {Path(f).name} into {agent.name}/{inbox.name}/")


def board(folders):
    """The lab board: tokens and time for each agent since its last reset."""
    print(f"{'agent':<12}{'path':<7}{'trigger':<13}{'model':<28}{'runs':>5}{'calls':>7}{'tokens in':>11}{'out':>8}{'seconds':>9}")
    for folder in folders:
        s = Path(folder) / "traces" / "summary.jsonl"
        if not s.exists():
            continue
        rows = [json.loads(l) for l in s.read_text().splitlines() if l.strip()]
        r0 = rows[-1]
        print(f"{r0['agent']:<12}{r0['path']:<7}{r0['trigger']:<13}{r0['model'][:27]:<28}{len(rows):>5}"
              f"{sum(r['model_calls'] for r in rows):>7}{sum(r['tokens_in'] for r in rows):>11,}"
              f"{sum(r['tokens_out'] for r in rows):>8,}{round(sum(r['seconds'] for r in rows), 1):>9}")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return
    cmd = argv[1]
    if cmd == "board":
        folders = argv[2:] or sorted(str(p) for p in (ROOT / "agents").iterdir() if p.is_dir())
        return board(folders)
    agent = Agent(argv[2])
    if cmd == "run":
        run(agent, " ".join(argv[3:]) or None)
    elif cmd == "reset":
        reset(agent)
    elif cmd == "drop":
        drop(agent, argv[3:])
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv)
