# Week 4 lab: comparing agent runs

An AI agent runs on a **harness**, a program you talk to that gives the **model** its instructions and tools. In this lab you give the same task to three agents:

1. **[Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) with model Opus 5.5**, hosted by Anthropic.
2. **[pi](https://pi.dev) with model Opus 5.5**: the same model, different harness.
3. **pi with Gemma 4**, running locally through [Ollama](https://ollama.com): different model, the same harness.

`run.py` runs the task, and `report.py` turns the agents' session logs into a report: time, speed, tokens, cost, automatic checks on the result, and a table for your own judgment.

## Setup (once)

You need Python 3.9 or newer (`python3 --version`).

#### 1. Claude Code

Log in with your Claude plan, then check:

```sh
claude auth status
```

Look for `"authMethod": "claude.ai"`. If it shows an API key instead, runs are billed to that key, not your plan. Check whether `ANTHROPIC_API_KEY` is set in your shell.

#### 2. Ollama and the Gemma model

Install Ollama from [ollama.com](https://ollama.com). pi doesn't run Gemma itself. It sends requests to the **Ollama server**, so that server has to be running whenever you run pi with Gemma, and also while you download the model. Start it in a separate terminal window and leave that window open:

```sh
ollama serve
```

Closing that window stops the server. If you have the Ollama app open, it already runs the server in the background. `ollama serve` then says "address already in use", which is fine.

Check that it's running:

```sh
curl http://localhost:11434     # should print: Ollama is running
```

Then download the model once, about 18 GB:

```sh
ollama pull gemma4:26b
```

#### 3. pi

```sh
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
```

That's all setup 3 needs: with the Ollama server running, `python3 run.py pi` uses Gemma on your computer.

#### 4. pi with cloud models

Setup 2 needs pi logged in to a cloud model with an **API key**. Keys are billed per token, separately from any Claude plan. Pick one:

**Anthropic API key (recommended).** Setup 2 then reaches Opus the same way Claude Code does, directly at Anthropic, so the only difference from setup 1 is the harness.

1. Create a key at [console.anthropic.com](https://console.anthropic.com). New accounts get a small amount of free credit.
2. Start `pi`, type `/login`, choose **Anthropic API key** and paste it. pi saves it, so you only do this once. Quit pi (*Ctrl+D*) and check:

```sh
pi auth check --provider anthropic     # should print: ready
```

**OpenRouter: one key for many models.** [OpenRouter](https://openrouter.ai) gives you Opus, Gemini and hundreds of other models with one account. In `/login`, choose **OpenRouter** and sign in in the browser, or paste a key from [openrouter.ai/keys](https://openrouter.ai/keys). OpenRouter passes each request on to the company that hosts the model. That's one step more than setup 1, so the harness comparison is slightly less clean.

**Gemini directly.** Get an API key from [Google AI Studio](https://aistudio.google.com/apikey). In `/login`, choose **Google** and paste it. With a school account, AI Studio may be turned off. If so, ask your school's IT whether they provide Gemini through Google Cloud (Vertex AI), which pi supports as `--provider google-vertex` (see [pi's provider docs](https://github.com/earendil-works/pi)), or use a personal Google account.

To check any setup without running it or spending anything, add `--dry-run`. It prints the folder name and the command.

> 💳 `/login` also offers **Anthropic**, which signs in with your Claude account. Your plan doesn't cover pi, though. Anthropic charges third-party apps to **extra usage**, a paid balance at [claude.ai/settings/usage](https://claude.ai/settings/usage). Without it, runs stop with "Third-party apps now draw from your extra usage, not your plan limits".

⚠️ Don't put API keys in your shell profile (`export ANTHROPIC_API_KEY=…` in `~/.zshrc`). Claude Code would pick up the key too and bill it instead of your plan. `/login` keeps the key to pi.

---

## Running

Run everything from this folder. The task is in `prompt.txt`, and all three setups get exactly that text.

**Watch one run (manual):**

```sh
python3 run.py claude                                            # 1. Claude Code + Opus 5.5
python3 run.py pi                                                # 2. pi + Gemma 4 (local)
python3 run.py pi --provider anthropic --model claude-opus-5-5   # 3. pi + Opus 5.5
```

The agent opens with the prompt already sent. You don't type or approve anything. When it's done, exit: `/exit` in Claude Code, *Ctrl+D* in pi.

**Several runs unattended (automatic):**

```sh
python3 run.py claude --auto 5
python3 run.py pi --provider anthropic --model claude-opus-5-5 --auto 5
python3 run.py pi --auto 5
```

You'll see one line per run, like `[2/5] runs/claude-opus5.5-medium/run3 … done in 91s`.

Using OpenRouter or Gemini for setup 2? Run `python3 run.py pi --provider openrouter --model anthropic/claude-opus-5.5`, or `--provider google --model gemini-3.1-pro-preview`. With Gemini, setups 1 and 2 differ in both harness and model, so you can't tell which one caused a difference.

> ⚠️ 🎲 **One run is one sample.** Agents vary from run to run, so do **3–5 runs per agent** before drawing conclusions.

### What each run does

- Everything goes under `runs/`, with one folder per setup and a new `runN` folder inside it for each run. The agent writes its result inside that folder:

  ```
  runs/
    claude-opus5.5-medium/    run1/  run2/  …
    pi-opus5.5-medium/        run1/  run2/  …
    pi-gemma4.26b-medium/     run1/  run2/  …
  ```

  A model reached through a go-between such as OpenRouter also gets its name: `runs/pi-openrouter-opus5.5-medium/`.
- Manual and automatic runs use the same prompt, model, effort and tool permissions, so you can mix them. For example, watch one run, then `--auto 4` for the rest.
- The agents don't see this folder's `CLAUDE.md` or your personal Claude Code setup (skills, MCP servers, hooks), so every run starts from the same place.

### Trying another model or effort level

```sh
python3 run.py claude --model claude-sonnet-5 --effort high
python3 run.py pi --effort low
```

A new model or effort level starts its own series of folders at `run1`. Effort levels:
- Claude Code: `low`, `medium`, `high`, `xhigh`, `max`
- pi: `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`

Both default to `medium`. To see which models pi can use, run `pi --list-models`.

---

## Reporting

```sh
python3 report.py
```

The script goes through the setups in lab order (Claude Code, then pi with a cloud model, then pi with a local model) and lists the matching folders in `runs/`. For each setup, type a folder's number and press Enter, or press Enter alone for the newest. All runs in that folder are used.

Each setup becomes one column. With several runs, the **bold** value in a cell is the median, the middle run, and the brackets show the lowest and highest run. The result checks count how many runs passed. All three setups need at least one run; if one is missing, the script tells you which command to run.

To leave out a run that went wrong, delete its `runN` folder.

The report is saved as `report.md`. Open it in a Markdown preview, for example in VS Code or on GitHub.

You can also name the folders, or single runs, directly. Each one becomes a column:

```sh
python3 report.py runs/claude-opus5.5-medium runs/pi-opus5.5-medium runs/pi-gemma4.26b-medium
python3 report.py runs/claude-opus5.5-medium/run3      # one run
python3 report.py LOG1.jsonl LOG2.jsonl                # any session logs, one column each
```

Other options:

| Option | What it does |
|---|---|
| `--md other.md` | save the report under another name (`--md -` prints it only) |
| `--no-timeline` | leave out the step-by-step traces |
| `--full` | the detailed report, one column per run: every counter, every step, and the recorded reasoning |

### Reading the report

1. **The numbers:**
   - *Latency:* time until the agent's first output.
   - *Throughput:* output tokens per second while waiting on the model.
   - Tokens and **cost**. Cost is what the tokens would cost at API list prices. Claude Code runs on a Claude plan aren't charged per token; they count toward your plan's usage limits. pi runs with Claude are charged, to your extra usage or your API key. Local models cost nothing per token.
2. **How good are the results?** Each row is a requirement from the prompt, checked automatically. For one run: ✅ every layer, ⚠️ at least half, ❌ fewer than half or missing. For several runs, the same marks count runs that passed, for example ⚠️ 4 of 6 runs. These checks test structure, not whether anything is true.
3. **Your evaluation.** Fill this table in yourself. Where your judgment disagrees with the checks is exactly what automated evaluation misses.
4. **Traces.** A link to each session log, and every step the agent took, collapsed under a toggle.

## Good to know

- **Manual and automatic runs mix.** A run you watched counts like any other run in its folder. Its time ends at the agent's last reply, not when you exit.
- **A run went wrong** (network error, you quit early)? Delete its `runN` folder. The report leaves it out, and the next run takes a new number.
- **Starting over?** Delete `runs/`, or just one setup's folder in it. Do this whenever you change `prompt.txt`, so runs with different prompts don't end up in the same folder.
- **Check a command before spending anything:** add `--dry-run` to see the folder and exact command without running it.
- **Session logs** are stored by the tools, not in this folder: Claude Code in `~/.claude/projects/`, pi in `~/.pi/agent/sessions/`. Deleting a run folder leaves its log there. The report ignores it, but logs can contain file contents and command output, so read a log before sharing it and delete old ones you don't need.
- **Local runs start slowly.** `run.py` loads the Gemma model before the first run so that load time isn't counted. If it says Ollama isn't running, run `ollama serve` in another terminal (or open the Ollama app).
- **Claude's reasoning isn't in the logs by default.** To log it, add `"showThinkingSummaries": true` to `~/.claude/settings.json`. What you get is a summary written by Anthropic, not the model's full reasoning. `run.py` starts Claude Code in safe mode, which may ignore this setting; if the report still says "Not logged", that's why. Gemma's reasoning is logged in full.

## Files

| File | What it is |
|---|---|
| `prompt.txt` | the task all three setups get |
| `run.py` | runs an agent on the task in a fresh folder |
| `report.py` | reads the session logs and writes `report.md` |
| `runs/` | one folder per setup, with a `runN` folder per run holding the agent's `stack.md` |
| `CLAUDE.md` | notes for Claude Code when working on these scripts, not used by the runs |
