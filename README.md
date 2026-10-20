# AI Agent Design, Fall 2026

A course on designing AI agents: programs that use a language model to decide what to do, then do it. Each week has a lab in its own folder, with a README that tells you how to run it.

The latest lab, Week 7, is a Job Agent that searches job boards for you every day, scores what it finds against your CV, and learns from your feedback. You can have it running in a few minutes: see [Week 7: start here](#week-7-start-here).

| Folder | Topic |
|---|---|
| [week4-agent-runs](week4-agent-runs/) | Run the same task with three agents and compare harness against model |
| [week5-minimal-agent](week5-minimal-agent/) | Workflows and agents on one small harness |
| [week6-agent-evals](week6-agent-evals/) | Build a golden set and measure how often an agent gets it right |
| [week7-job-agent](week7-job-agent/) | A job agent that runs daily in Claude's cloud, scores new postings against your CV, and suggests improvements from your verdicts |

## Week 7: start here

The Job Agent runs in Claude's cloud, so there is nothing to clone or install. You need a paid Claude plan (Pro or higher); each run uses your plan's usage.

1. Open [Claude Code](https://claude.ai/code), start a new session, and send:

   > Set up my Job Agent by following https://github.com/arikan/ai-agent-design-fall-2026/blob/main/week7-job-agent/SETUP.md

2. Tell Claude the roles, industries and location you're after. It creates your Job Agent artifact and daily run, and links you to the artifact.
3. In the artifact, follow the setup panel, then press **Start my agent**. Your first matches appear in a few minutes.

[Week 7's README](week7-job-agent/README.md) has the rest: how it works, the [guide](week7-job-agent/GUIDE.md) for daily use, and how to run it on your own computer.

## Getting the labs

New to the terminal, VS Code or git? [Terminal, VS Code and Git](BASICS.md) covers what the labs use.

Clone once:

```sh
git clone https://github.com/arikan/ai-agent-design-fall-2026.git
cd ai-agent-design-fall-2026
```

Each week, get the new folder:

```sh
git pull
```

Your own work, such as agent runs in `runs/` and generated `report.md` files, is ignored by git. It stays on your machine and never conflicts with updates. Don't edit the files that come with the repo: `git pull` stops if you've changed one. Copy it first and edit the copy. If a pull still stops, `git stash` puts your changes aside so the pull can finish.

## Setup (once)

From week 5 on, the labs run `mva.py`, which needs Python and, for cloud models, an API key. Do this once for the course. Claude Code and pi, which only week 4 uses, are set up in [week 4's README](week4-agent-runs/README.md#setup-once).

Week 7 is different: it doesn't use `mva.py` or an API key. Start it from [Week 7: start here](#week-7-start-here) above. To run it on your own computer instead, you also need [uv](https://docs.astral.sh/uv/getting-started/installation/); see [Run it locally](week7-job-agent/README.md#run-it-locally).

### Python

`python3 --version` must say 3.11 or newer. If it's older, install the latest Python from [python.org](https://www.python.org/downloads/). There is nothing else to install.

### API key

If you only use Ollama, which runs on your computer, skip this: it needs no key.

Get a key from one provider. API use always needs credit or a card on file, billed separately from chat plans like Claude or ChatGPT, except where free use is noted:

| Provider | Where to get a key | Line in `.env` file |
|---|---|---|
| **Anthropic** | [console.anthropic.com](https://console.anthropic.com) | `ANTHROPIC_API_KEY=` your key |
| **OpenAI** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | `OPENAI_API_KEY=` your key |
| **Gemini** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey). **Free tier available**, with rate limits and no card needed. Students may get more through [Google's student offer](https://blog.google/innovation-and-ai/products/gemini-app/student-offer-google-ai/). | `GEMINI_API_KEY=` your key |
| **OpenRouter** | [openrouter.ai/keys](https://openrouter.ai/keys). One key for hundreds of models, open-source and closed, including the latest. **Some are free**, offered by their providers, up to 50 requests a day. | `OPENROUTER_API_KEY=` your key |

Each week's folder reads the key from its own `.env` file, a plain text file of `NAME=value` lines; the week's README shows how to make it. The dot at the start of the name makes it a hidden file: Finder and `ls` don't show it (press Cmd-Shift-. in Finder, or run `ls -a`), but the VS Code Explorer does.

🔑 **Keep your key to yourself.** Git ignores `.env`, but that only protects you from commits. Never zip it into a submission, paste it into a chat, show it on a shared screen, or share one key with classmates. In your provider's console, set a monthly spend limit, so a leaked key can't cost much. If a key leaks, delete it there and make a new one.

VS Code may offer to enable `python.terminal.useEnvFile` once `.env` exists. Say no: `mva.py` already reads `.env` itself, and that setting would put your key into every VS Code terminal, where Claude Code would pick it up and bill it instead of your plan.

### Ollama

Ollama runs models on your computer, for free. Install and start it as in [week 4](week4-agent-runs/README.md#2-ollama-and-the-gemma-model). Each week's README says which model to pull.
