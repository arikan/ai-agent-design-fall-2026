# Job Agent

An AI agent that finds jobs for you and improves itself with your guidance. It reads your CV and preferences, collects new postings from job boards every day, scores them, and shows the best matches. You mark matches Good or Nope, and it suggests changes to its own profile. You decide which ones to keep.

## Start in the cloud

You need a paid Claude plan (Pro or higher). The daily run is a scheduled task on Claude's servers and uses your plan's usage.

1. Open [Claude Code](https://claude.ai/code), not the regular Claude chat. On a new session, before typing anything, let its cloud environment reach job boards (for safety it can reach only a few sites until you allow more):
   - Under the message box, click the first small button. It shows your environment's name, usually **Default**.
   - Hover over **Default** and click the settings icon on its right.
   - Set **Network access** to **Full** and save.
2. In that same screen, send:

   > Set up my Job Agent by following https://github.com/arikan/ai-agent-design-fall-2026/blob/main/week7-job-agent/SETUP.md

3. Claude first checks that it can reach a job board; if not, it tells you what to change and asks you to start again. Then tell it the roles, industries and location you're after. It creates your Job Agent artifact and daily run.
4. Open your artifact and press **Start my agent**. Your first matches appear in a few minutes.

Then read the [guide](GUIDE.md) for daily use, changing the agent, and an exercise.

It runs in Claude's cloud, so the Job Agent page is an artifact in your Claude account and the daily run is a scheduled task there. Changes you make on the page are saved there too.

To run it on your own computer instead, with any model, see [Start on your computer](#start-on-your-computer).

## Start on your computer

One command runs everything:

```bash
cd week7-job-agent
uv run jobagent serve
```

It opens http://localhost:8765, your Job Agent, with the course's 41 job boards and a starting profile.

**You need**

- Python 3.10 or newer
- [uv](https://docs.astral.sh/uv/getting-started/installation/), which installs the one dependency on first run
- [Claude Code](https://claude.com/claude-code), installed and signed in. It scores the posts, using your Claude account, so no API key is needed.

**Then**

1. **Profile tab:** your roles, industries, pay target and CV. The preview at the bottom shows which posts the next run would score.
2. **Run now.** The agent collects posts from every board, filters and ranks them, and the model scores the best few. The terminal shows the log; matches appear when it finishes.
3. **Judge** them Good or Nope. Then **Agent → Suggest changes**, apply what you agree with, and run again.

Everything is saved in `work/db` in this folder, as plain JSON files. Nothing leaves your computer except requests to job boards and to the model.

**Start over.** Stop the server (Ctrl-C), delete the `work` folder, and start it again. The next start seeds a fresh database from `defaults/`: the 41 boards and the starting profile. Git ignores `work`, so nothing else changes.

```bash
rm -rf work
uv run jobagent serve
```

To keep your profile and verdicts but clear the runs, delete only `work/db/matches`, `work/db/runs` and `work/db/postings`. The seed never overwrites what is already there.

**Other models.** Copy `.env.example` to `.env` and set `JOB_AGENT_MODEL`. The page records which model scored every post, so models can be compared by their agreement with you.

| `JOB_AGENT_MODEL` | Runs on | Needs |
|---|---|---|
| `claude` (default) | Claude Code on your computer | the `claude` command, signed in |
| `anthropic/claude-sonnet-4-5` | Anthropic API | `ANTHROPIC_API_KEY` |
| `openai/gpt-5-mini` | OpenAI API | `OPENAI_API_KEY` |
| `gemini/gemini-2.5-flash` | Google API | `GEMINI_API_KEY` |
| `openrouter/<vendor>/<model>` | OpenRouter | `OPENROUTER_API_KEY` |
| `ollama/gemma3` | [Ollama](https://ollama.com) on your computer | nothing; set `OLLAMA_HOST` if it isn't on port 11434 |

Any model name the provider accepts works. Small local models fail the quote check more often; the Runs tab shows how many scores were rejected and why.

**Every morning.** A cron line runs the agent while you sleep, and the page shows the results next time you open it:

```
47 7 * * * cd /path/to/week7-job-agent && uv run jobagent run
```

**Step by step**, to watch the parts work or change them: `uv run jobagent db config` writes `work/config.json` from `work/db`; then `uv run jobagent sources fetch work/config.json`, `uv run jobagent engine prepare work/config.json`, `uv run jobagent judge`, `uv run jobagent engine finish work/config.json`, and `uv run jobagent db export` followed by `uv run jobagent db apply` to put the results back. `uv run jobagent sources try examples/source.greenhouse.json` tries one job board; `uv run jobagent sources test` runs every adapter offline.

## How it works

```
 job boards ──► adapters ──► engine: collect, dedupe, filter ──► Claude: score ──► engine: rank ──► Job Agent page
 (Greenhouse,    (sources)     (engine prepare)                     (judgments)      (engine finish)     (matches, runs)
  Lever, Ashby…)
```

| Part | What it does |
|---|---|
| **Adapters** (`adapters/`) | One per kind of job board. Each knows how to fetch postings from that kind of board and turn them into one common shape. |
| **Sources** | Your list of boards: which adapter, plus its settings, like a company's board token. Adding a board is a new source, not new code. |
| **Engine** (`jobagent/engine.py`) | Deterministic code, never a model. Collects postings, removes duplicates, skips postings already seen, applies your filters and the limits, prepares the batch for judging, checks every judgment, and computes the weighted totals. |
| **Claude** | The only step that needs judgment: scores each posting on each of your dimensions, 1 to 5 or unknown, with a reason and a quote from the posting as evidence. |
| **Suggestions** (`jobagent/suggest.py`) | On request, or after every run if turned on: code gathers your Good and Nope verdicts and which dimensions disagree with them, the model proposes up to three Profile changes, and code checks them (a weight change must raise agreement on your judged posts). You apply them or not on the Agent tab. |
| **Job Agent artifact** | Where you set up searches (your CV and preferences), manage sources, judge matches, and read what every run did. |

Everything the engine decides is written to a trace, so any match can be traced back to the postings, settings and versions that produced it.

## In the cloud, after setup

The daily run is a Claude Code scheduled task that clones this repository and follows [`RUN.md`](RUN.md). [Start in the cloud](#start-in-the-cloud) sets it up. After that:

- The agent runs every morning, and new matches appear in your artifact.
- **Run now** starts a run any time, up to the daily limit.
- **Test** on a source runs just that source, so a new board can be checked before the next run.
- Each run keeps the day's collected posts in the artifact. The Profile tab ranks them live as you edit, and shows which posts the next run would score. Ranking is code; only scoring needs the model.
- Each run clones the repository fresh, so code changes reach the cloud on the next run.

## Make it yours

Most changes need no code: your profile, rubrics, weights, boards and scoring instructions are all in the artifact, and each change is saved as a version.

To change the code:

1. Fork this repository on GitHub. A public fork is simplest.
2. Change your fork: add an adapter, change the ranking in `jobagent/engine.py`, or edit the steps in `RUN.md`. Run `uv run jobagent sources test` and the rank test below before you push.
3. Point your daily run at your fork. In a Claude Code session, ask: *Change my "Job agent daily run" scheduled task to clone https://github.com/YOUR-NAME/ai-agent-design-fall-2026 instead.*

From then on, your runs use your code and your artifact updates from your fork's `console.html`. Course updates no longer reach you on their own; use **Sync fork** on GitHub to pull them in.

## Commands

| Command | What it does |
|---|---|
| `uv run jobagent engine rank-fixture` then `node tests/rank_test.js` | Check that the artifact's in-browser ranking matches the engine's |
| `uv run jobagent usage` | Token usage of the Claude session running it, from its transcript (each run records this) |
| `uv run jobagent` | Lists every command |
| `uv run jobagent serve` | The Job Agent page on your computer |
| `uv run jobagent run` | One whole run here: collect, rank, score with the model, write to `work/db` |
| `uv run jobagent suggest` | Suggest Profile changes from your verdicts, here |
| `uv run jobagent judge [--model …]` | Score `work/batch.json` with the model from `.env` |
| `uv run jobagent prepare` / `finish` | The cloud run's two halves: everything before Claude scores, and everything after |
| `uv run jobagent sources test` | Run every adapter against its saved responses, offline |
| `uv run jobagent sources try <source.json> [out.json]` | Run one source live and show a sample |
| `uv run jobagent find "<company>"` | Find a company's job board from its name, and test it |
| `uv run jobagent figure <url>` | Work out how to read a careers page, and test it |
| `uv run jobagent scout [--n 12]` | Experiment: one agent or a team of three scouts naming companies, each board found and measured against your profile |
| `uv run jobagent sources fetch <config.json>` | Fetch every enabled source into `work/fetched/` |
| `uv run jobagent sources domains <config.json>` | List the domains the enabled sources need |
| `uv run jobagent engine prepare <config.json>` | Collect, filter and prepare `work/batch.json` |
| `uv run jobagent engine finish <config.json>` | Check judgments, rank, write `work/results.json` |
| `uv run jobagent db config` / `export` / `apply` / `seed` | Convert between the database (`work/db`) and the run's files |

## Sources and adapters

Built in adapters: Greenhouse, Lever, Ashby, Workable, Getro (venture firm portfolio boards), JSON API, web page (CSS selectors), RSS. Two more types exist only as sources: the frozen corpus of 20 fictional postings for repeatable tests, and "check by hand" reminders for boards that block automated access.

**Adding a board.** On the Sources tab, paste the address of the page that lists the jobs, or type the company's name, and press **Add**. A Greenhouse, Lever, Ashby or Workable address is added and tested at once. A company name goes to the agent, which looks for the company's Greenhouse, Lever, Ashby or Workable board by name, then for a careers page on its own site, and in the cloud searches the web for it; whatever it finds is tested before it is added. Any other page goes to the agent: code looks for an embedded board or a feed, and failing that the model reads the page and proposes selectors, each proposal tested before it is kept. Pages that load their jobs with JavaScript can't be read this way; the agent says so and offers to keep the address as a reminder. **Add by hand** opens the full form.

**Starting sources.** A new Job Agent artifact starts with the boards in `defaults/agent.json`: company boards in AI, crypto and fintech, venture firm portfolio boards, and a few check-by-hand reminders for sites without a public feed. Turn off the ones that don't fit your search on the Sources tab. To change what every new artifact starts with, edit that file.

**When a source breaks**, the fix is usually in its settings, not code: new selectors for a web page, new field paths for a JSON API, a corrected board token. The artifact flags sources that fail or suddenly return nothing, and the daily run proposes fixes it has tested. You apply or discard them.

**To add an adapter type**, add a file in `jobagent/adapters/` with a class that subclasses `BaseSource` and implements `fetch()` and `normalize()`, register it in `jobagent/adapters/__init__.py`, and add a fixture in `jobagent/adapters/fixtures/` so `uv run jobagent sources test` covers it. The existing adapters are short and make good templates. In the artifact, a custom adapter can also be written as code for a single source.

**Requests go only to a source's own domains.** The code checks this. In the cloud, the environment's network setting is the real limit.

## Limits

Course limits live in `caps.json` and are enforced in code: the morning run always runs and you may start ten more a day by hand (a rolling 24 hours), three active searches, 1,000 postings read per source, 10,000 per run, 12 judged per search. Reading is cheap and done in code, so every fetched posting goes through your filters and the ranking; judging is what uses your plan, so that is the tight cap. The artifact can lower them, never raise them.

## Your data

- Your CV file never leaves your computer. The page extracts its text in your browser, you edit what the agent may read, and only that text is saved.
- On your computer, everything lives in `work/db`, which git ignores. In the cloud, searches, matches, verdicts, run records and the latest day's collected postings live in the Job Agent artifact's database on Claude's servers, readable only by you. Nothing personal goes into this repository.

## Known limits

- Getro boards list jobs without descriptions, and web page sources read only the listing unless a description selector is set; expect more unknown scores from these.
- Which postings get scored is decided by a cheap prefilter: your search's keywords (a keyword in the title counts double), plus word overlap with your CV. It decides what the agent sees, so choose keywords with care.
- Your verdicts drive the Agent tab's Feedback: agreement compares them with the agent's scores per version, and suggested changes propose edits to your Profile. Nothing changes until you apply it. Agreement is a signal from your own verdicts, not a fixed test set: each version is judged on different posts.

## Files

```
week7-job-agent/
├── README.md, GUIDE.md      this file, and the guide: daily use, changing the agent, an exercise
├── RUN.md, SETUP.md         what the cloud run follows, and what Claude follows to set it up
├── console.html             the Job Agent page, the same file locally and as the artifact
├── jobagent/               the Python package; `uv run jobagent` runs its command line (cli.py)
│   ├── serve.py             the page on your computer, with work/db as its database
│   ├── run.py               one run: on your computer, or the cloud's two halves
│   ├── sources.py           run sources through adapters
│   ├── engine.py            filter, rank, prepare the batch, check scores, total them
│   ├── judge.py, model.py   scoring with the model you choose
│   ├── suggest.py           suggested Profile changes from your verdicts
│   ├── dbio.py, localdb.py  the database <-> the run's files
│   ├── usage.py             a Claude session's token use
│   └── adapters/            one file per kind of job board, plus fixtures/
├── defaults/                starting agent settings and first search
├── corpus/postings.jsonl    20 fictional postings for repeatable tests
├── examples/                a sample config and a sample source
├── tests/                   the page's ranking checked against the engine's
├── caps.json                course limits
└── pyproject.toml, uv.lock
```
