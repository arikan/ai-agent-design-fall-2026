# Agent evals

Last week the task agent turned a folder of receipts into `report.md`, and you read one report. One run shows what an agent can do. It doesn't show how often it does it. Run the same agent twenty times and it will sometimes ask about the hotel and sometimes not, sometimes catch the duplicate and sometimes claim it twice.

This lab measures that. You write an answer key, `golden.jsonl`, that says what a correct run looks like, one case per line. Then `mva.py` runs the agent many times, each run in its own copy of the folder, and checks every run against every case:

```
python3 mva.py golden setups/task-agent     # draft an answer key from a run
python3 mva.py eval   setups/task-agent     # run it 20 times and grade each run
```

The harness is last week's `mva.py` with these two commands added. The setups are the same four, and the task agent's `harness.toml` adds one line, `eval_inbox`, the five receipts every eval run starts with.

```
setups/<setup>/
  spec.md           what the model reads (requested)
  harness.toml      what mva.py enforces (enforced)
  golden.jsonl      what a correct run looks like (expected): one case per line, checked by a person
```

## Setup (once)

📖 **New to the terminal, VS Code or git?** Read **[Terminal, VS Code and Git](../BASICS.md)** first. It covers the commands this lab uses, and you can keep it open as a reference while you work.

### 1. Get the folder

If you don't have the course repo yet, clone it as the [course README](../README.md#getting-the-labs) shows. Then, in the repo:

```
git pull
cd week6-agent-evals
```

Every `python3 mva.py …` command in this README runs from this folder.

### 2. Check Python

`python3 --version` must say 3.11 or newer. If it's older, install the latest Python from [python.org](https://www.python.org/downloads/). There is nothing else to install.

### 3. Add your API key

If you only use Ollama, which runs on your computer, skip this step: it needs no key.

Your API key goes in a file called `.env`, in this folder. It's a plain text file of `NAME=value` lines, which `mva.py` reads on every run. The dot at the start of the name makes it a hidden file: Finder and `ls` don't show it (press Cmd-Shift-. in Finder, or run `ls -a`), but the VS Code Explorer does.

Make it once, from the example that comes with the lab:

```
cp .env.example .env
```

Open `.env` in VS Code by clicking it in the Explorer, paste the key for the provider you use, and save. API use always needs credit or a card on file, billed separately from chat plans like Claude or ChatGPT, except where free use is noted:

| Provider | Where to get a key | Line in `.env` file |
|---|---|---|
| **Anthropic** | [console.anthropic.com](https://console.anthropic.com) | `ANTHROPIC_API_KEY=` your key |
| **OpenAI** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | `OPENAI_API_KEY=` your key |
| **Gemini** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey). **Free tier available**, with rate limits and no card needed. Students may get more through [Google's student offer](https://blog.google/innovation-and-ai/products/gemini-app/student-offer-google-ai/). | `GEMINI_API_KEY=` your key |
| **OpenRouter** | [openrouter.ai/keys](https://openrouter.ai/keys). One key for hundreds of models, open-source and closed, including the latest. **Some are free**, offered by their providers, up to 50 requests a day. | `OPENROUTER_API_KEY=` your key |

🔑 **Keep your key to yourself.** Git ignores `.env`, but that only protects you from commits. Never zip it into a submission, paste it into a chat, show it on a shared screen, or share one key with classmates. In your provider's console, set a monthly spend limit, so a leaked key can't cost much. If a key leaks, delete it there and make a new one.

VS Code may offer to enable `python.terminal.useEnvFile` once `.env` exists. Say no: `mva.py` already reads `.env` itself, and that setting would put your key into every VS Code terminal, where Claude Code would pick it up and bill it instead of your plan.

### 4. Pick the model

Each setup picks its model in its own `harness.toml`, near the top:

```toml
model = "anthropic/claude-sonnet-5"
# model = "openai/gpt-5-mini"
# model = "gemini/gemini-2.5-flash"
# model = "ollama/gemma3"                       # local & free
# model = "openrouter/z-ai/glm-5.3-flash"       # any model (incl. opensource) behind a router
```

The part before the `/` is the provider, and it must match the key you added. `ollama/` needs no key. To switch, put `#` in front of the current `model` line and remove it from the one you want, then save. Do this in all four: `setups/pipeline/`, `setups/scheduled-pipeline/`, `setups/task-agent/` and `setups/standing-agent/`.

**OpenRouter for free**: use `openrouter/openrouter/free`, or any model on [openrouter.ai/models](https://openrouter.ai/models) whose name ends in `:free`. Each model call counts as one request.

**Ollama**, free and on your computer: have Ollama running (set up in [week 4](../week4-agent-runs/README.md#setup-once)), pull the model once with `ollama pull gemma3`, and switch to the `ollama/gemma3` line.

The receipts are images, so the model must read images. Ollama models write their tool calls as JSON text, which the harness parses (`tool_mode = "text"`); you can see this in each run's trace, in the setup's `traces/` folder.

## Build the answer key

The task agent already comes with a checked answer key, `setups/task-agent/golden.jsonl`. Build your own first anyway, in a copy, so you see where a key comes from:

```
cp -r setups/task-agent setups/my-task-agent
rm setups/my-task-agent/golden.jsonl
python3 mva.py run    setups/my-task-agent
python3 mva.py golden setups/my-task-agent
```

`run` is last week's run: answer the agent's question in the terminal when it asks. `golden` reads that run's trace and the files it wrote, and drafts `setups/my-task-agent/golden.jsonl`. It prints which trace it drafted from. If you skip `run`, `golden` runs the agent once itself.

Open `golden.jsonl` in VS Code. Each line is one case:

```json
{"id": "trattoria-sole-menu-reason", "grader": "row_value", "settled": null, "note": "drafted from run 20261004-155416-manual.jsonl, verify by hand", "file": "report.md", "row": "trattoria_sole_menu.jpg", "column": "Reason", "any": ["This is a restaurant menu, not a receipt, no proof of purchase or amount paid."]}
```

This case says: in `report.md`, find the table row for `trattoria_sole_menu.jpg`, look in its Reason column, and pass if it contains that text. The draft holds the model's answers, not the right ones. Copied straight from one run, the key would grade every later run on whether it matches that run, mistakes and exact wording included. Correct it:

1. **Check each answer against the receipt.** Open the receipt itself. If the model got it wrong, write the right answer. If the case checks something that doesn't matter, delete the line.
2. **Loosen the wording.** The next run won't write the same sentence. Replace the long text in `any` with a few short words that any correct answer would contain: `["menu", "not a receipt", "no proof"]`. A number case uses `near` instead, and passes within 0.01.
3. **Add what the draft missed.** The draft only knows what this run did. If the agent should have asked about something and didn't, add a case for it. The graders are in [Make your own eval](#make-your-own-eval).
4. **Mark what you checked.** Change `settled` from `null` to `true` when you are sure of the answer, or to `false` when you checked it and the answer is still open: the spec could be read two ways, or you haven't decided. Rewrite `note` as a few words that say what a passing run does: the eval report shows it next to each score. For a `false` case, write the open question instead: `Cafe Luna latte, no business purpose stated: personal, so left out?`
5. **Fill in the answers.** The last line scripts the person the agent asks. Each `match` is a word that may appear in a question; write the `answer` you would give. Use words the question is sure to contain, like `harbor` and `hotel`.

Then compare yours with `setups/task-agent/golden.jsonl`.

## Run the eval

```
python3 mva.py eval setups/task-agent --runs 20
```

`eval` won't start while any case still has `settled: null`. It copies the setup 20 times into `setups/task-agent/evals/<time>/run-1/` … `run-20/`, puts the five receipts from `eval_inbox` in each copy's inbox, and runs four at a time. Nobody types: when the agent asks, the `answers` line replies, and you can see each question and answer in the terminal. Each run then gets graded against every case. A run the harness stopped, or that crashed, fails every case.

When it finishes, it prints a table and saves it as `summary.md` in `setups/task-agent/evals/<time>/`. See [example-summary.md](example-summary.md), from 20 runs of `anthropic/claude-sonnet-5`.

The rows that need you come first, and `next` says what to do. In the example, `duplicate-left-out` failed once: `run-1/report.md` shows the agent caught the duplicate but called the original the copy. Is that a miss, or is the case too strict? And the ○ rows show the agent called both coffees personal every time: the spec leaves that open, so the agent decided for you.

## Change the specification, run eval again

Copy the setup, change one sentence of the policy in `spec.md`, and run it again:

```
cp -r setups/task-agent setups/task-agent-b
```

In `setups/task-agent-b/spec.md`, under Sources, add one line to the policy:

```
- Coffee during a work session is a business meal.
```

```
python3 mva.py eval setups/task-agent-b --runs 5
```

Five runs is enough to see a case move, not to prove it moved. Compare the new `summary.md` with the last one. Watch `cafe-luna-personal`: it was undecided, and now the spec takes a side, so settle it in `setups/task-agent-b/golden.jsonl`. The `kaffeehaus` cases move too, which is why one line of policy needs the whole key rerun. Change only one thing between two evals, or you won't know which change moved which case.

## Swap the model, run eval again

```
python3 mva.py eval setups/task-agent --runs 20 --model openai/gpt-5-mini
```

`--model` replaces the model for this eval only, the way `MVA_MODEL` does in `.env`; `harness.toml` stays the same. The same key with a different model gives you a different report. Compare it with the last one: which cases did the cheaper model stop holding, and how much did it save? `--jobs 2` runs fewer at once if a provider limits you, and Ollama runs one at a time on most computers anyway.

## What the runs generate

```
setups/<setup>/
  traces/             one file per run, with every model call and tool call, plus summary.jsonl
  golden.jsonl        the answer key: drafted by golden, corrected by you
  evals/<time>/       one eval: summary.md (the report), results.jsonl, and run-1/ … run-<n>/
  expenses.csv        pipelines: one row per file
  report.md           task agent: the report
  memory.md           standing agent: its memory
  filed/  review/     standing agent: where it sorted files
  pending/            standing agent: questions waiting for a person
```

`run` and `reset` keep `golden.jsonl` and `evals/`. Git keeps `golden.jsonl` and ignores `evals/`, the same as `traces/`.

`python3 mva.py usage` still compares the setups' last runs. Eval runs aren't counted there; their totals are on the eval's last line.

## Make your own agent

An agent is two files, so making your own means copying a folder and rewriting `spec.md` for your job and `harness.toml` for what it may touch; `mva.py` stays the same.

What an agent can reach:

- Reads: images (jpg, png, gif, webp), text (txt, md, csv, log, json, toml), and PDFs with an `anthropic/` model, from the folders `harness.toml` lets it read.
- Writes: creates, appends, moves and deletes files, only in the folders `harness.toml` allows.
- Asks a person, and notifies you in the terminal and `notifications.log`.
- Starts by you, a timer, or a new file.
- Cannot reach the web, email, other apps, or run code. To add that, see [Inside mva.py](#inside-mvapy).

Example jobs: a pipeline that writes alt text for every image in a folder (set `output_lines = "all"` to keep answers longer than one line), a task agent that summarizes a folder of interview notes, a standing agent that files whatever lands in its `screenshots/` folder.

### 1. Copy a folder

```
cp -r setups/task-agent setups/my-agent
```

Start from `setups/task-agent`. Move to another cell only when the work forces you. To make your own workflow, copy `setups/pipeline` instead.

### 2. Turn off the reset

In `setups/my-agent/harness.toml`, set `fresh = false`. Every run otherwise deletes everything in the folder except `spec.md`, `harness.toml` and `traces/`, including your files and the agent's memory. To start clean by hand, run `python3 mva.py reset setups/my-agent`.

### 3. Rewrite the spec

Rewrite `spec.md` for your step.

### 4. Edit the harness

Edit the rest of `harness.toml` for your agent.

### 5. Add your files and run it

Put your files in `setups/my-agent/inbox/`, then:

```
python3 mva.py run setups/my-agent
```

## Make your own eval

The graders don't know your job. A key is plain data, so the same five graders check alt text, interview summaries or filed screenshots as well as receipts.

```
python3 mva.py run    setups/my-agent
python3 mva.py golden setups/my-agent
```

Correct `golden.jsonl` as in [Build the answer key](#build-the-answer-key), then:

```
python3 mva.py eval setups/my-agent --runs 10
```

If `cp -r` brought the task agent's key along, delete it before `golden`, or add `--force` to draft over it. Each eval run starts from a copy of your folder as it is now (with `fresh = false`), and only that copy changes. Your files stay as they are. That includes what your last run wrote: delete old outputs such as `report.md` before an eval, or a run that writes nothing will be graded on the old file. To start every run with only some of the files, list them in `harness.toml`: `eval_inbox = ["a.png", "b.png"]`.

Every case has an `id`, a `grader`, `settled` and a `note`, plus the fields its grader reads. All matching ignores case.

**`text_contains`** passes if the file contains any of the strings. For an alt text pipeline that must describe the chart as a chart:
`{"id": "chart-named", "grader": "text_contains", "settled": true, "note": "Alt text calls it a chart", "file": "alt.csv", "any": ["bar chart", "chart showing"]}`

**`text_lacks`** passes if the file contains none of them. For interview summaries that must leave out the participants' names:
`{"id": "anonymous", "grader": "text_lacks", "settled": true, "note": "No participant named", "file": "summary.md", "any": ["Dana", "Whitfield"]}`

**`row_value`** finds the table row (markdown or CSV) that contains `row`, takes the cell under the header that contains `column`, and passes if that cell has a number within 0.01 of `near`, or contains any string in `any`. Rows are found by what they say, never by their position, so the agent can put them in any order. For the alt text pipeline, whose `expenses.csv` becomes `alt.csv` with a `file,alt` header:
`{"id": "q3-revenue", "grader": "row_value", "settled": true, "note": "Q3 chart alt text names revenue", "file": "alt.csv", "row": "chart_q3.png", "column": "alt", "any": ["revenue"]}`

**`file_in`** passes if the file exists in the run's folder after the run. For a standing agent that files screenshots by month:
`{"id": "filed-october", "grader": "file_in", "settled": true, "note": "October screenshot filed under 2026-10", "path": "filed/2026-10/screenshot_0412.png"}`

**`tool_call`** passes if the trace shows a call to `tool` (one name or a list) whose path contains `args_contain`; for a tool without a path, such as `ask`, any argument counts. With `before`, the call must also come before a second matching call. With `"never": true`, it passes only if no such call happens, allowed or denied: trying counts. For the screenshot agent, which must never touch the private folder:
`{"id": "private-untouched", "grader": "tool_call", "settled": true, "note": "Never touches screenshots/private/", "tool": ["move_file", "write_file", "delete_file"], "args_contain": "screenshots/private/", "never": true}`

If your agent asks questions, add the answers line, so that eval runs never stop to wait for you: `{"answers": [{"match": "private", "answer": "Leave it where it is."}]}`. The first `match` found in the question gives the answer, and a question that matches none gets "No.". An agent started by a timer or a new file still queues its questions in `pending/`, as it would with nobody there.

## Safety

The harness only lets a setup touch files inside its own folder, and only the folders listed in `harness.toml`. Deleting is off unless you add the tool, and the standing agent has it denied on purpose. Runs cost money on paid APIs, and an eval is many runs: try `--runs 2` first, read the cost on the last line, then multiply before you run 20.

The receipts are specimens: invented businesses, generated by `tools/make_receipts.py`. To work on your own images, make your own agent.

## Inside mva.py

`mva.py` is one file, standard library only, written to be read top to bottom in the order of the agent architecture.

| Box | Section |
|---|---|
| Context | `assemble_context`: the spec, memory, and tool descriptions |
| Router | `route`: `anthropic/…`, `openai/…`, `gemini/…`, `ollama/…`, `openrouter/…` |
| Model call | `call_model`: one HTTP request |
| Result | `parse_result`: text, and tool calls parsed out |
| Tool | `TOOLS`: what the agent can touch |
| Guardrail | `guard`: runs before every tool, whatever the model decided |
| Feedback | `run_goal`: every result goes back into the context |
| Trace | `Trace`: every run leaves a file |
| Trigger | `run`: you, a timer, or a new file |
| Grader | `GRADERS`: five checks, each reading one finished run folder and one case |
| Answer key | `draft_golden`: drafts `golden.jsonl` from the latest run, for a person to correct |
| Eval | `run_eval`: N runs in their own copies, graded; `eval_summary` writes the table, what needs you first |

To extend it:

- A tool: write a function, add it to `TOOLS` with its arguments and description, list it in the agent's `tools`, and if it reads or writes files, add it to `READS` or `WRITES` so `guard` checks its paths.
- A model provider: add a prefix in `route` that returns an Anthropic- or OpenAI-style endpoint; if it needs a key, send it in `call_model`.
- A trigger: add a case in `run`.
- A grader: write a function that takes the run folder and the case and returns True or False, and add it to `GRADERS`.
