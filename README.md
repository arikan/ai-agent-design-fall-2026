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

## Weeks 4 to 6

These labs run on your computer, from a clone of this repo. Each week's README starts with its own setup: Python, and an API key or Ollama. New to the terminal, VS Code or git? [Terminal, VS Code and Git](BASICS.md) covers what the labs use.
