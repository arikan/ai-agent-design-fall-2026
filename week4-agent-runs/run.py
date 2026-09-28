#!/usr/bin/env python3
"""Run the task in prompt.txt with one agent, in a fresh folder, the same way every time.

Usage:
  python3 run.py claude              one run you watch; the prompt is sent for you, exit when it is done
  python3 run.py pi
  python3 run.py claude --auto 5     five runs back to back, nothing to type
  python3 run.py pi --model gemma4:12b --effort high    another setup; starts its own series of folders
  python3 run.py pi --provider anthropic --model claude-opus-5-5     pi with a cloud model
  python3 run.py pi --provider google --model gemini-3.1-pro-preview
  python3 run.py pi --provider openrouter --model anthropic/claude-opus-5.5
  python3 run.py claude --dry-run     show the folder and command, run nothing

Each run gets its own folder, runs/<setup>/runN, where the setup is harness-model-effort, e.g.
runs/claude-opus5.5-medium/run1 or runs/pi-gemma4.26b-medium/run3. A model reached through a go-between such as
OpenRouter also gets the provider in its name: runs/pi-openrouter-opus5.5-medium/run1. A different model or effort
starts a new setup folder at run1. Manual and --auto runs use the same prompt, settings and tool permissions, so they
can be compared together.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request

# The setups. Change a model or effort here, or per run with --model / --effort.
SETUPS = {
    "claude": {"model": "claude-opus-5-5", "effort": "medium"},
    "pi": {"model": "gemma4:26b", "effort": "medium", "provider": "ollama"},
}
EFFORTS = {
    "claude": ["low", "medium", "high", "xhigh", "max"],
    "pi": ["off", "minimal", "low", "medium", "high", "xhigh", "max"],
}
# Claude Code tools that run without asking. Anything else that changes the machine is denied (dontAsk mode);
# read-only shell commands such as whoami are always allowed by Claude Code itself. pi has no permission prompts.
CLAUDE_TOOLS = [
    "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch",
    "Bash(uname:*)", "Bash(sw_vers:*)", "Bash(sysctl:*)", "Bash(curl -I:*)", "Bash(dig:*)", "Bash(whois:*)",
]
OLLAMA_URL = "http://localhost:11434"
HOME_PROVIDERS = {"anthropic", "google", "ollama"}  # left out of folder names
# How to log pi in to each cloud provider, shown when pi isn't logged in to it.
PI_LOGINS = {
    "anthropic": "choose  Anthropic API key  and paste a key from console.anthropic.com",
    "openrouter": "choose OpenRouter and sign in in the browser (or paste a key from openrouter.ai/keys)",
    "google": "choose Google and paste a Gemini API key from aistudio.google.com/apikey",
    "google-vertex": "set up Google Cloud credentials (see pi's docs on Google Vertex AI)",
}
HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, "runs")  # runs/<setup>/runN, next to this script wherever it is started from


def model_slug(model):
    """claude-opus-5-5 -> opus5.5, gemma4:26b -> gemma4.26b. Dashes are kept for separating the name's parts."""
    m = model.lower().split("/")[-1]
    m = m[len("claude-"):] if m.startswith("claude-") else m
    m = re.sub(r"^([a-z]+)-(?=\d)", r"\1", m)  # opus-5-5 -> opus5-5
    return re.sub(r"[-:]", ".", m)


def next_run_dir(setup):
    """runs/<setup>/runN with the next free N."""
    folder = os.path.join(RUNS, setup)
    names = os.listdir(folder) if os.path.isdir(folder) else []
    taken = [int(m.group(1)) for d in names if (m := re.fullmatch(r"run(\d+)", d))]
    return os.path.join(folder, f"run{max(taken, default=0) + 1}")


def command(harness, cfg, prompt, auto):
    """The agent's command line. The prompt goes first: --allowedTools takes every value after it."""
    if harness == "claude":
        return (
            ["claude", prompt]
            + (["-p"] if auto else [])
            + ["--safe-mode", "--model", cfg["model"], "--effort", cfg["effort"]]
            + ["--permission-mode", "dontAsk", "--allowedTools", *CLAUDE_TOOLS]
        )
    return (
        ["pi"]
        + (["-p"] if auto else [])
        + ["--no-context-files", "--provider", cfg["provider"], "--model", cfg["model"], "--thinking", cfg["effort"]]
        + [prompt]
    )


def warm_up(model):
    """Check Ollama is running and has the model, then load it before the first run, so its load time
    isn't counted as the agent's latency."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=10) as r:
            pulled = {m["name"] for m in json.load(r).get("models", [])}
    except OSError:
        sys.exit("Ollama isn't running. Start it: run  ollama serve  in another terminal (or open the Ollama app).")
    if model not in pulled and f"{model}:latest" not in pulled:
        sys.exit(f"{model} isn't downloaded yet. Run:  ollama pull {model}")
    print(f"Loading {model} in Ollama…", flush=True)
    body = json.dumps({"model": model, "keep_alive": "30m"}).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=body, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=300).read()


def check_pi_login(provider, model):
    """Stop early, with instructions, when pi has no credentials for a cloud provider."""
    done = subprocess.run(
        ["pi", "auth", "check", "--provider", provider, "--model", model, "--json"], capture_output=True, text=True
    )
    try:
        ready = json.loads(done.stdout).get("status") == "ready"
    except json.JSONDecodeError:
        ready = False
    if not ready:
        sys.exit(
            f"pi isn't logged in to {provider}. Start  pi , type  /login , "
            f"{PI_LOGINS.get(provider, 'choose ' + provider + ' and sign in or paste an API key')}. Then run this again."
        )


def main():
    ap = argparse.ArgumentParser(description="Run prompt.txt with one agent in a fresh folder.")
    ap.add_argument("harness", choices=sorted(SETUPS))
    ap.add_argument("--model", help="model to use instead of the one in SETUPS")
    ap.add_argument("--effort", help="reasoning effort instead of the one in SETUPS")
    ap.add_argument("--provider", help="pi only: where the model runs, e.g. ollama, anthropic, openrouter, google")
    ap.add_argument("--auto", type=int, metavar="N", help="run N times without a person, one after another")
    ap.add_argument("--dry-run", action="store_true", help="show the folder and command without running anything")
    a = ap.parse_args()

    cfg = dict(SETUPS[a.harness])
    cfg["model"] = a.model or cfg["model"]
    cfg["effort"] = a.effort or cfg["effort"]
    if a.provider and a.harness != "pi":
        sys.exit("--provider is for pi; Claude Code always uses Anthropic.")
    if a.provider:
        cfg["provider"] = a.provider
        if not a.model:
            sys.exit(f"Give the model to use with {a.provider}, e.g. --model claude-opus-5-5 or --model gemini-3.1-pro-preview")
    if cfg["effort"] not in EFFORTS[a.harness]:
        sys.exit(f"--effort for {a.harness} is one of: {', '.join(EFFORTS[a.harness])}")
    with open(os.path.join(HERE, "prompt.txt"), encoding="utf-8") as f:
        prompt = f.read().strip()
    # A pi model reached through a go-between (OpenRouter, Copilot, Vertex, ...) gets the provider in its name,
    # so it forms its own series; a model at its own home (Anthropic, Google, Ollama) doesn't need it.
    routed = a.harness == "pi" and cfg["provider"] not in HOME_PROVIDERS
    where = [cfg["provider"].replace("-", ".")] if routed else []
    setup = "-".join([a.harness, *where, model_slug(cfg["model"]), cfg["effort"]])

    if a.dry_run:
        print(f"Folder:  {os.path.relpath(next_run_dir(setup), HERE)}")
        print("Command: " + " ".join(shlex.quote(x) for x in command(a.harness, cfg, prompt, bool(a.auto))))
        return
    if a.harness == "pi" and cfg["provider"] == "ollama":
        warm_up(cfg["model"])
    elif a.harness == "pi":
        check_pi_login(cfg["provider"], cfg["model"])
    for i in range(a.auto or 1):
        run_dir = next_run_dir(setup)
        os.makedirs(run_dir)
        shown = os.path.relpath(run_dir, HERE)
        if a.auto:
            print(f"[{i + 1}/{a.auto}] {shown} … ", end="", flush=True)
        else:
            print(f"\nStarting {shown}. The prompt is sent for you; exit the agent when it is done.\n")
        start = time.time()
        done = subprocess.run(
            command(a.harness, cfg, prompt, bool(a.auto)),
            cwd=run_dir,
            stdout=subprocess.DEVNULL if a.auto else None,
        )
        took = f"{time.time() - start:.0f}s"
        if a.auto:
            print(f"done in {took}" if done.returncode == 0 else f"exited with code {done.returncode} after {took}")
    print("\nCompare the runs with: python3 report.py")


if __name__ == "__main__":
    main()
