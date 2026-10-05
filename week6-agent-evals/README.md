# Agent evals

Last week the task agent turned a folder of receipts into `report.md`, and you read one report. One run shows what an agent can do. It doesn't show how often it does it. Run the same agent twenty times and it will sometimes ask about the hotel and sometimes not, sometimes catch the duplicate and sometimes claim it twice.

This lab measures that. You write a golden set, `golden.jsonl`, that says what a correct run looks like, one case per line. Then `mva.py` runs the agent many times, each run in its own copy of the folder, and checks every run against every case:

```
python3 mva.py golden setups/task-agent     # draft a golden set from a run
python3 mva.py eval   setups/task-agent     # run it 20 times and grade each run
```

The harness is last week's `mva.py` with these two commands added. The other three setups are unchanged from last week and not used here; the task agent's `harness.toml` adds one line, `eval_inbox`, the five receipts every eval run starts with.

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

Do the [course setup](../README.md#setup-once) once first: Python 3.11 or newer, an API key, and Ollama if you use it.

### 1. Get the folder

If you don't have the course repo yet, clone it as the [course README](../README.md#getting-the-labs) shows. Then, in the repo:

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

Open `.env` in VS Code by clicking it in the Explorer, paste your key after its provider's name, and save. Where to get a key, and how to keep it safe, is in the [course setup](../README.md#api-key).

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

**Ollama**, free and on your computer: have Ollama running (see the [course setup](../README.md#ollama)), pull the model once with `ollama pull gemma3`, and switch to the `ollama/gemma3` line.

The receipts are images, so pick a model that reads images.

## What is in a golden set

An eval has four parts:

1. **An input**, which goes to the agent. In this lab: the five receipts, the spec, and the scripted answer to the agent's question.
2. **An output**, which the agent produces. In this lab: `report.md` and the trace, one pair per run.
3. **A golden answer**, which says what the output should have been. In this lab: the lines of `golden.jsonl`.
4. **A score**, which says how close the output came. In this lab: the table in `summary.md`.

For a chatbot the output is one reply. For an agent it is two things: what it wrote and what it did. So a golden answer here can be about the report, or about the record of the agent's actions.

You add a golden answer when you have seen the agent do something and you know whether it was right. That happens three times:

1. After the first run, when you read `report.md` row by row and know the answer for each.
2. After an eval, when a failing run shows the agent doing something the golden set never looked at.
3. After a change to the spec, when there is a new right answer.

The golden set grows from reading.

Each golden answer is one line, with two parts:

```json
{"note": "trattoria_sole_menu Menu left out: not a receipt",
 "expect": {"in": "report.md", "near": "trattoria_sole_menu.jpg", "says_any": ["menu", "not a receipt"]}}
```

- **`note`** is the answer said to a person: the receipt's name, then what a correct run does.
  - Write it as the sentence you would say to a colleague.
  - If you would have to ask them instead, say what the check counts, then ask: `harbor_hotel_boston Claimed in full. Should the $12.50 breakfast be left out?` A question marks the case open: the count shows how often runs took that reading, not a pass or fail.
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

## Build a golden set

**Run the agent once.** Make your own task agent from the two files that define it, and run it:

```
mkdir setups/my-task-agent
cp setups/task-agent/spec.md setups/task-agent/harness.toml setups/my-task-agent/
python3 mva.py run setups/my-task-agent
```

The agent may ask you about the hotel bill. Type your answer in the terminal. When it finishes, the run has left two things in `setups/my-task-agent/`: `report.md`, what the agent wrote, and a trace in `traces/`, what it did.

**Draft the golden set from that run:**

```
python3 mva.py golden setups/my-task-agent
```

This reads `report.md` and the trace, and writes `setups/my-task-agent/golden.jsonl`. Open that file in VS Code. It has a line for each thing `report.md` says about the five receipts in `eval_inbox` (the other four receipts are not part of the eval), a line that checks the agent never changed `inbox/`, and a last line with answers. Every line copies what the agent did in your one run, right or wrong. Your job is to correct them.

Here is the line for the menu:

```json
{"note": "trattoria_sole_menu Reason: drafted from run 20261004-155416-manual.jsonl, verify?", "expect": {"in": "report.md", "near": "trattoria_sole_menu.jpg", "column": "Reason", "says_any": ["This is a restaurant menu, not a receipt, no proof of purchase or amount paid."]}}
```

In words: in `report.md`, find the row for `trattoria_sole_menu.jpg`. Its Reason cell must contain this sentence.

**1. Decide if the agent was right.** Open the image the agent read, `setups/my-task-agent/inbox/trattoria_sole_menu.jpg`, and its row in `report.md`. The image is a menu, not a receipt, and the agent left it out. That is right, so keep the line. If the agent got a receipt wrong, change the line to the right answer. If a line checks something you don't care about, delete it.

**2. Shorten `says_any`.** The next run won't write the same sentence. Keep a few words that any correct answer would contain:

```
before:  "says_any": ["This is a restaurant menu, not a receipt, no proof of purchase or amount paid."]
after:   "says_any": ["menu", "not a receipt"]

before:  "says_any": ["Duplicate copy of cafe_luna_0914.jpg (same receipt, same charge) — would double-count if included."]
after:   "says_any": ["duplicate"]

before:  "says_any": ["Personal snack (flat white & Franzbrötchen), no business purpose. Amount was €7.60 (≈ $8.36 at 1 EUR = 1.10 USD) but excluded regardless."]
after:   "says_any": ["personal", "no business purpose"]
```

**3. Rewrite the note.** The eval's summary shows this note for the line. Keep the receipt's name, then say what a correct run does:

```
before:  "note": "trattoria_sole_menu Reason: drafted from run 20261004-155416-manual.jsonl, verify?"
after:   "note": "trattoria_sole_menu Menu left out: not a receipt"
```

If you can't decide what is right, say what the line checks, then ask your question. The hotel bill includes a $12.50 breakfast, and the policy doesn't say whether it is reimbursed:

```
before:  "note": "harbor_hotel_boston Amount: drafted from run 20261004-155416-manual.jsonl, verify?"
after:   "note": "harbor_hotel_boston Claimed in full. Should the $12.50 breakfast be left out?"
```

Do steps 1 to 3 for every receipt line. The `inbox/` line is already right; only rewrite its note: `"Never tries to change inbox/"`.

**4. Add what your run did not show.** The draft only checks what happened in your run. A correct run asks about the hotel before it writes `report.md`. Add this line above the last line:

```json
{"note": "harbor_hotel_boston Asked about before the report was written", "expect": {"did": "ask", "mentions": "harbor", "before": {"did": "write_file", "mentions": "report.md"}}}
```

**5. Fill in the last line.** In an eval nobody is at the keyboard, so this line answers the agent's questions for you. The draft leaves both parts blank. `match` is a word every hotel question will contain; `answer` is what every run should hear. A blank answer is sent as "No.".

```
before:  {"answers": [{"match": "", "answer": ""}]}
after:   {"answers": [{"match": "harbor", "answer": "Approved as a school event; follow the policy on the meal."}]}
```

**6. Compare** your file with the finished one that comes with the lab, `setups/task-agent/golden.jsonl`, receipt by receipt.

## Run the eval

An eval is many paid runs: try `--runs 2` first and read the cost on the last line.

```
python3 mva.py eval setups/my-task-agent --runs 20
```

Each run works in its own copy, and the `answers` line replies when the agent asks. The result is `evals/<time>/summary.md` in `setups/my-task-agent/evals/<time>/`, like [example-summary.md](example-summary.md).

## Change the specification, run eval again

```
cp -r setups/my-task-agent setups/my-task-agent-b
```

In `setups/my-task-agent-b/spec.md`, under Sources, add one line:

```
- Meals on a hotel bill are not reimbursed: claim the room and its taxes only.
```

Run it again (5 runs would be enough to see the change):

```
python3 mva.py eval setups/my-task-agent-b --runs 5
```

Compare the new `evals/<time>/summary.md` with the previous one. The hotel row should be the only change: before, some runs claimed the full $412.02 and some left out the breakfast; now none claims it in full. The other rows stay the same.

The summary still shows the hotel row as an open question, because its note in `golden.jsonl` still asks one. The spec answers it now, so close the case: in `setups/my-task-agent-b/golden.jsonl`, replace that line with a statement and the new amount:

```json
{"note": "harbor_hotel_boston Claimed without the breakfast", "expect": {"in": "report.md", "near": "harbor_hotel_boston.jpg", "column": "Amount", "value": 399.52}}
```

## Swap the model, run eval again

Pick a model whose provider key is in your `.env`, as in [Pick the model](#3-pick-the-model).

```
python3 mva.py eval setups/my-task-agent --runs 20 --model openai/gpt-5-mini
```

Compare the new `summary.md` with the last one.

## Make your own eval

Bring the agent you made in [week 5](../week5-minimal-agent/README.md#make-your-own-agent):

```
cp -r ../week5-minimal-agent/setups/my-agent setups/
python3 mva.py run    setups/my-agent
python3 mva.py golden setups/my-agent
```

Fix `golden.jsonl` as in [Build a golden set](#build-a-golden-set), then:

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
