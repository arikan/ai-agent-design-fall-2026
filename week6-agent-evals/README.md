# Agent evals

Last week the task agent turned a folder of receipts into `report.md`, and you read one report. One run shows what an agent can do. It doesn't show how often it does it. Run the same agent twenty times and it will sometimes ask about the hotel and sometimes not, sometimes catch the duplicate and sometimes claim it twice.

An eval measures how often an agent gets each thing right. A test runs a program once on an input and checks the output against the answer: pass or fail. An eval does the same to a program with a model in it, many times, because the model won't do the same thing every run. Its result is a rate, how often the output matched the golden answer, and the rate is what tells you whether a change to the spec or the model helped.

This lab runs one on the task agent, in three steps:

```
python3 mva.py golden setups/my-task-agent     # 1. draft a golden set from one run, then correct it
python3 mva.py eval   setups/my-task-agent     # 2. run it 20 times and grade every run
open setups/my-task-agent/evals/<latest>/summary.md   # 3. read the summary
```

A golden set, `golden.jsonl`, holds the golden answers: what a correct run looks like, one line per case. The eval runs the agent many times on the same input, each run in its own copy of the folder, and checks every run's output, what it wrote and what it did, against every line. The summary is the score: one table, how often each line passed, and what to do next.

The harness is last week's `mva.py` with `golden` and `eval` added. The other three setups are unchanged from last week and not used here; the task agent's `harness.toml` adds one line, `eval_inbox`, the five receipts every eval run starts with.

```
setups/<setup>/
  spec.md           what the model reads (requested)
  harness.toml      what mva.py enforces (enforced)
  golden.jsonl      what a correct run looks like (expected): one case per line, checked by a person
  report.md         what the last run wrote
  traces/           one file per run: every model call and tool call
  evals/<time>/     one eval: summary.md, and run-1/ … run-<n>/
```

## Setup (once)

📖 **New to the terminal, VS Code or git?** Read **[Terminal, VS Code and Git](../BASICS.md)** first. It covers the commands this lab uses, and you can keep it open as a reference while you work.

`python3 --version` must say 3.11 or newer. If it's older, install the latest Python from [python.org](https://www.python.org/downloads/). There is nothing else to install.

### 1. Get the folder

If you don't have the course repo yet, clone it once with `git clone https://github.com/arikan/ai-agent-design-fall-2026.git`. Then, in the repo:

```
git pull
cd week6-agent-evals
```

Every `python3 mva.py …` command in this README runs from this folder.

### 2. Add your API key

If you only use Ollama, skip this step.

Make the `.env` file in this folder from the example that comes with the lab:

```
cp .env.example .env
```

Open `.env` in VS Code by clicking it in the Explorer, paste your key after its provider's name, and save. Where to get a key, and how to keep it safe, is in [week 5's setup](../week5-minimal-agent/README.md#2-add-your-api-key). If you set up week 5, copy its `.env` here instead.

### 3. Pick the model

Each setup picks its model in its own `harness.toml`, near the top:

```toml
model = "anthropic/claude-sonnet-5"
# model = "openai/gpt-5-mini"
# model = "gemini/gemini-2.5-flash"
# model = "ollama/gemma3"                       # local & free
# model = "openrouter/z-ai/glm-5.3-flash"       # any model (incl. opensource) behind a router
```

The part before the `/` is the provider, and it must match the key you added. `ollama/` needs no key. To switch, put `#` in front of the current `model` line and remove it from the one you want, then save.

**OpenRouter for free**: use `openrouter/openrouter/free`, or any model on [openrouter.ai/models](https://openrouter.ai/models) whose name ends in `:free`. Each model call counts as one request.

**Ollama**, free and on your computer: have Ollama running (install and start it as in [week 4](../week4-agent-runs/README.md#2-ollama-and-the-gemma-model)), pull the model once with `ollama pull gemma3`, and switch to the `ollama/gemma3` line.

The receipts are images, so pick a model that reads images.

## Step 1 · Draft a golden set from one run, then correct it

Make your own task agent from the two files that define it, and draft a golden set from it:

```
mkdir setups/my-task-agent
cp setups/task-agent/spec.md setups/task-agent/harness.toml setups/my-task-agent/
python3 mva.py golden setups/my-task-agent
```

`golden` runs the agent once if it hasn't run yet. The agent may ask you about the hotel bill: type your answer in the terminal. The run leaves two things in `setups/my-task-agent/`: `report.md`, what the agent wrote, and a trace in `traces/`, what it did. `golden` reads both and writes `golden.jsonl`: a line for each thing `report.md` says about the five receipts in `eval_inbox` (the other four receipts are not part of the eval), a line that checks the agent never changed `inbox/`, and a last line for answers.

**Every line copies what the agent did in your one run, right or wrong**, and its note says `verify?`. The eval refuses to start while a note still says that. Your job is to correct every line. Open `golden.jsonl` in VS Code. Here is the draft line for the menu:

```json
{"note": "trattoria_sole_menu Reason: drafted from run 20261004-155416-manual.jsonl, verify?", "expect": {"in": "report.md", "near": "trattoria_sole_menu.jpg", "column": "Reason", "says_any": ["This is a restaurant menu, not a receipt, no proof of purchase or amount paid."]}}
```

In words: in `report.md`, find the row for `trattoria_sole_menu.jpg`. Its Reason cell must contain this sentence. For each receipt line:

**1. Decide if the agent was right.** Open the image the agent read, `setups/my-task-agent/inbox/trattoria_sole_menu.jpg`, and its row in `report.md`. The image is a menu, not a receipt, and the agent left it out. That is right, so keep the line. If the agent got a receipt wrong, change the line to the right answer. The hotel bill is the one to watch: it includes a $12.50 breakfast, and the policy says to claim room and tax only, $399.52. If your run claimed the full $412.02, change the `value`. If a line checks something you don't care about, delete it.

**2. Shorten `says_any`.** The next run won't write the same sentence. Keep a few words that any correct answer would contain:

```
before:  "says_any": ["This is a restaurant menu, not a receipt, no proof of purchase or amount paid."]
after:   "says_any": ["menu", "not a receipt"]

before:  "says_any": ["Duplicate copy of cafe_luna_0914.jpg (same receipt, same charge) — would double-count if included."]
after:   "says_any": ["duplicate"]

before:  "says_any": ["Personal snack (flat white & Franzbrötchen), no business purpose. Amount was €7.60 (≈ $8.36 at 1 EUR = 1.10 USD) but excluded regardless."]
after:   "says_any": ["personal", "no business purpose"]
```

**3. Rewrite the note.** The summary shows this note for the line. Keep the receipt's name, then say what a correct run does:

```
before:  "note": "trattoria_sole_menu Reason: drafted from run 20261004-155416-manual.jsonl, verify?"
after:   "note": "trattoria_sole_menu Menu left out: not a receipt"
```

If you can't decide what is right, say what the line counts, then ask your question. The café receipts have no business purpose on them, and the agent left them out without asking. The spec says to ask only above $200, so is that right?

```
before:  "note": "cafe_luna_0914 Reason: drafted from run 20261004-155416-manual.jsonl, verify?"
after:   "note": "cafe_luna_0914 Left out as personal. Should it have asked instead?"
```

A note that ends in `?` marks the case open: the summary shows how often runs did that, not a pass or fail.

Do 1 to 3 for every receipt line. The `inbox/` line is already right; only rewrite its note: `"Never tries to change inbox/"`.

**4. Add what your run did not show.** The draft only checks what happened in your run. A correct run asks about the hotel before it writes `report.md`. Add this line above the last line:

```json
{"note": "harbor_hotel_boston Asked about before the report was written", "expect": {"did": "ask", "mentions": "harbor", "before": {"did": "write_file", "mentions": "report.md"}}}
```

**5. Fill in the last line.** In an eval nobody is at the keyboard, so this line answers the agent's questions for you. The draft leaves both parts blank. `match` is a word every hotel question will contain; `answer` is what every run should hear. A blank answer is sent as "No.".

```
before:  {"answers": [{"match": "", "answer": ""}]}
after:   {"answers": [{"match": "harbor", "answer": "Approved as a school event; follow the policy on the meal."}]}
```

**6. Compare** your file with the finished one that comes with the lab, `setups/task-agent/golden.jsonl`, receipt by receipt. What each key means is in [The golden set, line by line](#the-golden-set-line-by-line).

## Step 2 · Run it 20 times and grade every run

An eval is many paid runs: try `--runs 2` first and read the cost on the last line.

```
python3 mva.py eval setups/my-task-agent
```

This runs the agent 20 times (`--runs` changes that), each run in its own copy of the folder with the five receipts of `eval_inbox`. The `answers` line replies when the agent asks. When every run has ended, `mva.py` checks each run's output, the files it wrote and the trace of its tool calls, against every line of `golden.jsonl`, and writes `setups/my-task-agent/evals/<time>/summary.md` next to the runs, `run-1/` to `run-20/`.

## Step 3 · Read the summary, change one thing, run again

```
open setups/my-task-agent/evals/<latest>/summary.md
```

[example-summary.md](example-summary.md) is one from the finished golden set. Each row is one line of the golden set: how many runs passed it, and what to do next. ✓ passed every run. ✗ failed in some: open those runs and read what the agent wrote and did, then decide which is wrong, the agent or the check. ○ is an open question: a pass only shows what the agent did; decide it in the spec.

Two rows need you. The hotel row may be ✗: open a failing run's `report.md`. In our runs the agent followed the policy but listed the hotel night by night, and the check reads the first row that names the receipt, $179.00. The agent was right; the check was too narrow. The line is what to fix, not the spec. The café rows are ○: the agent left both out as personal every time, but the spec only says to ask above $200, so whether it should have asked is undecided. The agent is not wrong; the spec is. So decide it.

**Change the spec.** Copy your setup and add one line to its policy:

```
cp -r setups/my-task-agent setups/my-task-agent-b
```

In `setups/my-task-agent-b/spec.md`, under Sources:

```
- A meal with no business purpose on the receipt is personal: leave it out, no need to ask.
```

The spec decides it now, so close the two cases: in `setups/my-task-agent-b/golden.jsonl`, rewrite their notes as statements, `cafe_luna_0914 Left out as personal` and the same for `kaffeehaus_berlin`. Run it again (5 runs are enough) and compare the two summaries:

```
python3 mva.py eval setups/my-task-agent-b --runs 5
```

The counts should not move: the agent already did this. The marks do, ○ to ✓, because the spec now says it is right. That is what closing a case means. If you decide the other way, that a cheap meal with no purpose on it deserves a question, the spec line says so, and the golden set lines become `did: ask` lines like the hotel's.

**Swap the model.** Pick a model whose provider key is in your `.env`, as in [Pick the model](#3-pick-the-model), and compare again:

```
python3 mva.py eval setups/my-task-agent --model openai/gpt-5-mini
```

**Grow the golden set.** You add a line when you have seen the agent do something and you know whether it was right. That happens three times: after the first run, when you read `report.md` row by row; after an eval, when a failing run shows the agent doing something the golden set never looked at; and after a change to the spec, when there is a new right answer. The golden set grows from reading.

## The golden set, line by line

Each golden answer is one line, with two parts:

```json
{"note": "trattoria_sole_menu Menu left out: not a receipt",
 "expect": {"in": "report.md", "near": "trattoria_sole_menu.jpg", "says_any": ["menu", "not a receipt"]}}
```

- **`note`** is the answer said to a person: the receipt's name, then what a correct run does. Write it as the sentence you would say to a colleague. If you would have to ask them instead, say what the check counts, then ask; a note ending in `?` marks the case open.
- **`expect`** is the same answer said to the computer. It takes one of two forms:
  1. **About what the agent wrote:**
     - `in` is the output file to check, such as `report.md`.
     - `near` limits the check to the line or table row that mentions some text, usually a receipt's file name.
     - Then what should be there, one of:
       - `says_any`: a list of words; one is enough. Use short words any correct answer would contain, not the sentence one run happened to write.
       - `says_all`: every word must appear.
       - `says_none`: none may appear.
       - `value`: a number, matched within a cent.
       - `exists: true`: the file is there at all.

       Add `column` to pick the table heading, with any of these.
  2. **About what the agent did:**
     - `did` is a tool name, or a list.
     - `mentions` is a word that must appear in what the agent gave the tool.
     - `before` is a second call that must come later, as in the ask before the write.
     - `never: true` turns it around: pass only if no such call happened, whether the harness allowed it or not.

Matching ignores upper and lower case.

**The last line** scripts the person the agent asks, so eval runs don't stop to wait for you:

```json
{"answers": [{"match": "harbor", "answer": "Approved as a school event; follow the policy on the meal."}]}
```

Each `match` is a word to look for in the agent's question; the first one found gives its `answer`. Answer only what is asked: an answer that settles an open question turns that open case into a pass.

Most eval tools keep the golden answer as one value and put the comparison in code. This lab puts the comparison in the golden set, so you can read what each case checks without reading `mva.py`. Anthropic's [Building evals](https://platform.claude.com/cookbook/misc-building-evals) has the four parts and the three ways to grade.

## Make your own eval

Bring the agent you made in [week 5](../week5-minimal-agent/README.md#make-your-own-agent):

```
cp -r ../week5-minimal-agent/setups/my-agent setups/
python3 mva.py golden setups/my-agent
```

Correct `golden.jsonl` as in [Step 1](#step-1--draft-a-golden-set-from-one-run-then-correct-it), then:

```
python3 mva.py eval setups/my-agent --runs 10
```

Each run starts from your folder as it is, so delete old outputs such as `report.md` first. To give every run the same inbox, list the files in `harness.toml`: `eval_inbox = ["a.png", "b.png"]`.

## Inside mva.py

The harness is [week 5's](../week5-minimal-agent/README.md#inside-mvapy). This week adds:

| Box | Section |
|---|---|
| Grader | `grade_wrote` and `grade_did`, one for what the agent wrote, one for what it did |
| Golden set | `draft_golden`: drafts `golden.jsonl` from the latest run, for a person to correct |
| Eval | `run_eval`: N runs in their own copies, graded; `eval_summary` writes the table |

To add a comparison: add its key to `WROTE` and `VERDICTS`, and a branch in `grade_wrote` that returns True or False.
