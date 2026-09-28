# AI Agent Design, Fall 2026

Code and instructions for the course labs, one folder per week. Each folder has its own README: start there.

| Week | Folder | Topic |
|---|---|---|
| 4 | [week4-agent-runs](week4-agent-runs/) | Run the same task with three agents and compare harness against model |
| 5 | [week5-minimal-agent](week5-minimal-agent/) | A minimal working agent |
| 6 | week6-evals | Evaluating agents (coming) |

## Getting the labs

Clone once:

```sh
git clone <repo URL>
cd ai-agent-design-fall-2026
```

Each week, get the new folder:

```sh
git pull
```

Your own work, such as agent runs in `runs/` and generated `report.md` files, is ignored by git. It stays on your machine and never conflicts with updates. Don't edit the files that come with the repo: `git pull` stops if you've changed one. Copy it first and edit the copy. If a pull still stops, `git stash` puts your changes aside so the pull can finish.

The one-time tool setup (Claude Code, Ollama, pi) is in [week 4's README](week4-agent-runs/README.md#setup-once). Later weeks reuse it.
