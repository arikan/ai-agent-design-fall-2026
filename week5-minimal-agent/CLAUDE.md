# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Week 5 of the course repo (`ai-agent-design-fall-2026`): `mva.py`, a minimum viable agent harness. It is a single file, stdlib only, and needs Python 3.11+ (`tomllib`). It exists to be read by students: each numbered section comment in `mva.py` (`# ---- 1. context`, `2. router`, … `8. trace`) is one box of the Week 3 agent architecture, and the README has a table that maps each box to a function. Keep that structure, keep the file free of third-party packages, and update the README table when a function it names is renamed or moved. There is no build, lint or test suite. Each week's folder is self-contained and doesn't import from other weeks.

## Commands

```sh
python3 mva.py reset agents/task      # wipe outputs, re-seed inbox/, restore memory
python3 mva.py run   agents/task      # optional trailing words replace the harness.toml `start` message
python3 mva.py drop  agents/standing receipts/extras/cafe_luna_0921.jpg   # feed a running watcher (2nd terminal)
python3 mva.py board                  # tokens/time per agent, from traces/summary.jsonl
python3 -m py_compile mva.py          # the only offline check
```

Every `run` makes real model calls. Pick the model with `model = "anthropic/…" | "ollama/…" | "openrouter/<vendor>/<model>"` in `harness.toml`. The keys are `ANTHROPIC_API_KEY` and `OPENROUTER_API_KEY`. `need_key` takes them from the environment first, then from `.env` next to `mva.py` (git-ignored; students copy `.env.example`). The key is never put into `os.environ`, so it doesn't leak into Claude Code or other child processes, and `.env` sits outside every agent folder, so no agent's tools can read it. Never read or print a student's `.env`. `OLLAMA_HOST` overrides `localhost:11434`. `ollama/gemma3` is the free way to exercise a change. There is no dry-run mode.

## How it fits together

- **An agent is a folder** under `agents/`. `spec.md` is what the model reads ("requested"). `harness.toml` is what `mva.py` enforces ("enforced"). The split is the lesson, so rules that must hold belong in `harness.toml`/`guard`, not only in the spec. For example, task's "never change inbox/" is enforced by leaving `inbox` out of `write`, and standing offers `delete_file` but puts it in `deny` on purpose, to show a denial in the trace.
- **The Autonomy Grid is two keys.** `path = "steps"` runs `run_steps`: code loops over the files, makes one model call per file with no tools, and code appends the first non-fence line of the reply as a CSV row after the filename. `path = "goal"` runs `run_goal`: a tool loop until `finish`, a reply with no tool calls, `max_turns`, or `max_seconds`. `trigger` (`manual` / `every` / `on_new_file`) is dispatched in `run()`. `every` remembers processed filenames in `.processed`. `on_new_file` ignores files already present at start, polls every `poll` seconds (default 2) and starts one goal run per new file.
- **Internal message format.** Content is a list of harness-neutral blocks (`{"type":"text"}` / `{"type":"image","media_type","data"}`). Messages have roles `user`, `assistant` (`text` + `calls`) and `tool` (`results`). `to_anthropic` and `to_openai` convert at call time. Ollama and OpenRouter both go through the OpenAI-compatible path. On that path, images from tool results are re-sent as a following user message, because OpenAI tool messages carry text only.
- **Tool modes.** `tool_mode` is `native` (API tool calling) or `text`. Ollama models default to `text`: `text_protocol` adds a JSON calling convention to the system prompt, and `parse_text_call` pulls out the first `{…}` object, one call per reply. It can be overridden with `tool_mode` in `harness.toml`.
- **Tools and guardrail.** `TOOLS` is the registry: `fn`, `args` (every arg is a required string, and `schema()` is generated from it) and `about`. A tool is offered only if it is listed in the agent's `tools`. `guard` runs before every call and checks: the tool exists, it is offered, it isn't denied, all args are present, `READS` args are under `read + write`, and `WRITES` args are under `write`. All paths go through `Agent.file`, which rejects anything outside the agent folder. A new tool needs a `TOOLS` entry and, if it touches paths, `READS`/`WRITES` entries, or the guard won't check its paths. Tool exceptions and denials go back to the model as results; they don't crash the run.
- **`ask` depends on the trigger.** With `manual` it blocks on `input()`. Otherwise it writes the question to `ask_queue/` (default `pending/`) and tells the model not to act.
- **Traces.** Each run appends JSONL events (`context`, `result`, `tool`, `denied`, `step`, `end`) to `traces/<stamp>-<label>.jsonl`, plus one line to `traces/summary.jsonl`, which is all `board` reads. Later weeks (evals) read these, so treat event names and summary fields as an interface.

## Gotchas

- `reset` deletes everything in the agent folder except `KEEP` (`spec.md`, `harness.toml`, `policy.md`, `memory.start.md`). A new hand-written file in an agent folder is lost on the next reset unless it's added to `KEEP`. `seed = true` copies every file directly in `receipts/` (not `extras/`) into the inbox. `memory.md` is overwritten from `memory.start.md`.
- `receipts/` holds deliberate test cases: a duplicate (`cafe_luna_0914 (1).jpg`), a menu that isn't a receipt, foreign currency, a blurry photo, a rotated one, a handwritten one, an over-$200 hotel. Don't "clean them up". They are invented businesses with a specimen footer.
- `tools/make_receipts.py` regenerates them. It is the one script that needs Pillow, and it hardcodes Linux DejaVu font paths (`/usr/share/fonts/truetype/dejavu/`), so it won't run on macOS as-is.
