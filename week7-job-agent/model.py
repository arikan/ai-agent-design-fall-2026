"""One function, `complete(system, user)`, for the two steps that need a model: scoring and suggestions.

Which model, in order: the `--model` flag, `JOB_AGENT_MODEL` in the environment or in `.env` next to this file.
Default: `claude`, which runs the Claude Code command line (`claude -p`) with your Claude login, no key needed.
Any other model is called through its API, in the same form as the course's mva.py:

  claude                        Claude Code on this computer, your subscription (default)
  anthropic/claude-sonnet-4-5   Anthropic API, needs ANTHROPIC_API_KEY
  openai/gpt-5-mini             OpenAI API, needs OPENAI_API_KEY
  gemini/gemini-2.5-flash       Gemini, needs GEMINI_API_KEY
  openrouter/<vendor>/<model>   OpenRouter, needs OPENROUTER_API_KEY
  ollama/gemma3                 Ollama on this computer, no key
"""

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT = "claude"
KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY"}


def dotenv():
    env, pairs = HERE / ".env", {}
    if env.exists():
        for line in env.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and not k.strip().startswith("#"):
                pairs[k.strip()] = v.strip().strip("\"'")
    return pairs


def setting(name, default=None):
    return os.environ.get(name) or dotenv().get(name) or default


def chosen(flag=None):
    return flag or setting("JOB_AGENT_MODEL") or DEFAULT


def route(model):
    provider, _, name = model.partition("/")
    if provider == "anthropic":
        return "anthropic", name, "https://api.anthropic.com/v1/messages"
    if provider == "ollama":
        return "openai", name, setting("OLLAMA_HOST", "http://localhost:11434").rstrip("/") + "/v1/chat/completions"
    if provider == "openai":
        return "openai", name, "https://api.openai.com/v1/chat/completions"
    if provider == "gemini":
        return "openai", name, "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    if provider == "openrouter":
        return "openai", name, "https://openrouter.ai/api/v1/chat/completions"
    raise SystemExit(f"unknown model '{model}': use claude, or anthropic/, openai/, gemini/, ollama/, openrouter/")


def need_key(var):
    key = setting(var)
    if not key:
        raise SystemExit(f"no {var}: copy .env.example to .env and paste your key after {var}=")
    return key


def complete(system, user, model=None, max_tokens=8000):
    """The model's reply as text, plus how it was reached: {"model", "input_tokens", "output_tokens"}."""
    model = chosen(model)
    if model == "claude":
        return claude_cli(system, user)
    kind, name, url = route(model)
    if kind == "anthropic":
        body = {"model": name, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": user}]}
        headers = {"x-api-key": need_key(KEYS["anthropic"]), "anthropic-version": "2023-06-01"}
    else:
        body = {"model": name, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        headers = {}
        provider = model.partition("/")[0]
        if provider in KEYS:
            headers["Authorization"] = "Bearer " + need_key(KEYS[provider])
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"model call failed ({e.code}): {e.read().decode()[:600]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"cannot reach {url}: {e.reason}")
    if kind == "anthropic":
        text = "".join(b.get("text", "") for b in data.get("content", []))
        usage = data.get("usage", {})
        return text, {"model": name, "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}
    text = data["choices"][0]["message"]["content"] or ""
    usage = data.get("usage", {})
    return text, {"model": name, "input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens")}


def claude_cli(system, user):
    """Claude Code's command line, signed in with your Claude account. The reply is its final text."""
    exe = shutil.which("claude")
    if not exe:
        raise SystemExit("the `claude` command isn't installed. Install Claude Code (https://claude.com/claude-code), "
                         "or set JOB_AGENT_MODEL to an API model such as anthropic/claude-sonnet-4-5 in .env")
    cmd = [exe, "-p", "--output-format", "json", "--system-prompt", system, "--tools", ""]
    r = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise SystemExit(f"claude -p failed: {(r.stderr or r.stdout)[:600]}")
    try:
        out = json.loads(r.stdout)
        text = out.get("result") if isinstance(out, dict) else None
        usage = (out.get("usage") or {}) if isinstance(out, dict) else {}
        model = next(iter((out.get("modelUsage") or {}).keys()), None) if isinstance(out, dict) else None
        return text or r.stdout, {"model": model or "claude", "input_tokens": usage.get("input_tokens"),
                                  "output_tokens": usage.get("output_tokens")}
    except json.JSONDecodeError:
        return r.stdout, {"model": "claude", "input_tokens": None, "output_tokens": None}


def json_block(text):
    """The JSON in a reply, with or without a code fence."""
    t = text.strip()
    if "```" in t:
        t = t.split("```", 2)[1]
        t = t[t.find("\n") + 1:] if t.startswith(("json", "JSON")) else t
        t = t.rsplit("```", 1)[0]
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0] or [0])
    return json.loads(t[start:])
