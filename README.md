# AI Agent Design, Fall 2026

A course on designing AI agents: programs that use a language model to decide what to do, then do it. Each week has a lab in its own folder, with a README that tells you how to run it.

The latest lab, Week 7, is a Job Agent: an AI agent that finds jobs for you and improves itself with your guidance. Run it in Claude's cloud or on your own computer: see [Week 7: start here](#week-7-start-here).

| Folder | Topic |
|---|---|
| [week4-agent-runs](week4-agent-runs/) | Run the same task with three agents and compare harness against model |
| [week5-minimal-agent](week5-minimal-agent/) | Workflows and agents on one small harness |
| [week6-agent-evals](week6-agent-evals/) | Build a golden set and measure how often an agent gets it right |
| [week7-job-agent](week7-job-agent/) | A job agent that collects postings daily, scores them against your CV, and suggests changes to its profile from your Good and Nope verdicts. Runs in Claude's cloud or on your computer |

## Week 7: start here

**In the cloud.** You need a paid Claude plan (Pro or higher); each run uses your plan's usage.

1. Open [Claude Code](https://claude.ai/code), not the regular Claude chat. On a new session, before typing anything, let its cloud environment reach job boards (for safety it can reach only a few sites until you allow more):
   - Under the message box, click the first small button. It shows your environment's name, usually **Default**.
   - Hover over **Default** and click the settings icon on its right.
   - Set **Network access** to **Full** and save.
2. In that same screen, send:

   > Set up my Job Agent by following https://github.com/arikan/ai-agent-design-fall-2026/blob/main/week7-job-agent/SETUP.md

3. Claude first checks that it can reach a job board; if not, it tells you what to change. Then tell it the roles, industries and location you're after. It creates your Job Agent artifact and a daily run.
4. Open your artifact and press **Start my agent**. Your first matches appear in a few minutes.

**On your computer.** With Python 3.10+, [uv](https://docs.astral.sh/uv/getting-started/installation/) and [Claude Code](https://claude.com/claude-code) signed in (or another model set in `.env`):

```bash
cd week7-job-agent
uv run jobagent serve
```

It opens your Job Agent at http://localhost:8765.

[Week 7's README](week7-job-agent/README.md) has the rest: how it works, other models, starting over, and the [guide](week7-job-agent/GUIDE.md) for daily use and an exercise.

## Weeks 4 to 6

These labs run on your computer, from a clone of this repo. Each week's README starts with its own setup: Python, and an API key or Ollama. New to the terminal, VS Code or git? [Terminal, VS Code and Git](BASICS.md) covers what the labs use.
