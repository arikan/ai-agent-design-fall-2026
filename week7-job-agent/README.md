# Job Agent

An AI agent that finds jobs for you and improves itself with your guidance.

It takes your CV and preferences as a profile, and periodically collects new postings from job boards. It filters and scores them, and shows the best matches.

It is a self-improving agent with your feedback. You mark the matching job posts as Good or Nope, and these verdicts measure how well it agrees with you. Then it suggests changes to what it reads: your rubrics, weights, roles and keywords. Each suggestion you accept is saved as a new version and used from the next run, so you can see whether it helped.

It runs two ways:

- **In Claude's cloud**, once a day, even when your laptop is closed. You set it up and use it from the Job Agent artifact.  [Run it in Claude's cloud](#run-it-in-claudes-cloud).
- **On your own computer**, step by step, to see how it works or change it. [Run it locally](#run-it-locally).

## Start here

> **You need a paid Claude plan (Pro or higher).** The daily run is a Claude Code scheduled task on Claude's servers, which the free plan doesn't include. Each run uses your plan's usage.

1. Open [Claude Code](https://claude.ai/code) and start a new session.
2. Send this prompt:

   > Set up my Job Agent by following https://github.com/arikan/ai-agent-design-fall-2026/blob/main/week7-job-agent/SETUP.md

3. Answer Claude's question about the roles, industries and location you're after. Claude creates your Job Agent artifact and its daily run, then links you to the artifact.
4. In the artifact, follow the setup panel: allow the daily run to reach job sites (one network setting), then press **I've changed it, check my setup**.
5. When the light turns green, press **Start my agent**. Your first matches appear in a few minutes.

Then read the [guide](GUIDE.md): what to do each day, how to change the agent, and an exercise.

## How it works

```
 job boards ──► adapters ──► engine: collect, dedupe, filter ──► Claude: score ──► engine: rank ──► Job Agent page
 (Greenhouse,    (sources.py)  (engine.py prepare)                  (judgments)      (engine.py finish)  (matches, runs)
  Lever, Ashby…)
```

| Part | What it does |
|---|---|
| **Adapters** (`adapters/`) | One per kind of job board. Each knows how to fetch postings from that kind of board and turn them into one common shape. |
| **Sources** | Your list of boards: which adapter, plus its settings, like a company's board token. Adding a board is a new source, not new code. |
| **Engine** (`engine.py`) | Deterministic code, never a model. Collects postings, removes duplicates, skips postings already seen, applies your filters and the limits, prepares the batch for judging, checks every judgment, and computes the weighted totals. |
| **Claude** | The only step that needs judgment: scores each posting on each of your dimensions, 1 to 5 or unknown, with a reason and a quote from the posting as evidence. |
| **Suggestions** (`suggest.py`) | On request, or after every run if turned on: code gathers your Good and Nope verdicts and which dimensions disagree with them, the model proposes up to three Profile changes, and code checks them (a weight change must raise agreement on your judged posts). You apply them or not on the Agent tab. |
| **Job Agent artifact** | Where you set up searches (your CV and preferences), manage sources, judge matches, and read what every run did. |

Everything the engine decides is written to a trace, so any match can be traced back to the postings, settings and versions that produced it.

## Run it locally

### Requirements

- Python 3.10 or newer
- [uv](https://docs.astral.sh/uv/getting-started/installation/), which installs the one dependency (beautifulsoup4) for you
- [Claude Code](https://claude.com/claude-code), for the scoring step

### 1. Test the adapters offline

```bash
cd week7-job-agent
uv run sources.py test
```

Each adapter runs against a saved response in `adapters/fixtures/`. All eight should print `ok`. The first `uv run` sets up the environment.

### 2. Try one live source

```bash
uv run sources.py try examples/source.greenhouse.json
```

You should see how many postings were fetched and kept, and three samples. Change the board token in the file to try another company. This is also how you check a source after fixing it.

### 3. Fetch every source and prepare a run

`examples/config.example.json` holds one search and three sources. Copy it and edit the CV text, filters and dimensions to your own:

```bash
mkdir -p work
cp examples/config.example.json work/config.json
uv run sources.py fetch work/config.json
uv run engine.py prepare work/config.json
```

`fetch` prints one line per source. `prepare` writes two files:

- `work/batch.json`: the postings Claude will score, with your dimensions and rubrics
- `work/state.json`: the trace so far, including what the filters dropped and why

### 4. Score with Claude

Open the folder in Claude Code and ask:

> Judge work/batch.json following its matcher_instructions and answer_format, and write work/judgments.json. Evidence must be copied exactly from each posting.

### 5. Rank

```bash
uv run engine.py finish work/config.json
```

`work/results.json` holds the ranked matches and the full run record. If any judgment was rejected, for example because its evidence isn't in the posting, the trace says why.

Locally, nothing is written to the Job Agent artifact. That step needs a Claude session with access to your artifact, which the cloud run has.

## Run it in Claude's cloud

The daily run is a Claude Code scheduled task that clones this repository and follows [`RUN.md`](RUN.md). [Start here](#start-here) sets it up. After that:

- The agent runs every morning, and new matches appear in your artifact.
- **Run now** starts a run any time, up to the daily limit.
- **Test** on a source runs just that source, so a new board can be checked before the next run.
- Each run keeps the day's collected posts in the artifact. The Profile tab ranks them live as you edit, and shows which posts the next run would score. Ranking is code; only scoring needs the model.
- Each run clones the repository fresh, so code changes reach the cloud on the next run.

## Make it yours

Most changes need no code: your profile, rubrics, weights, boards and scoring instructions are all in the artifact, and each change is saved as a version.

To change the code:

1. Fork this repository on GitHub. A public fork is simplest.
2. Change your fork: add an adapter, change the ranking in `engine.py`, or edit the steps in `RUN.md`. Run `uv run sources.py test` and the rank test below before you push.
3. Point your daily run at your fork. In a Claude Code session, ask: *Change my "Job agent daily run" scheduled task to clone https://github.com/YOUR-NAME/ai-agent-design-fall-2026 instead.*

From then on, your runs use your code and your artifact updates from your fork's `console.html`. Course updates no longer reach you on their own; use **Sync fork** on GitHub to pull them in.

## Commands

| Command | What it does |
|---|---|
| `uv run engine.py rank-fixture` then `node tests/rank_test.js` | Check that the artifact's in-browser ranking matches the engine's |
| `uv run usage.py` | Token usage of the Claude session running it, from its transcript (each run records this) |
| `uv run run.py prepare` / `finish` | The cloud run's two halves: everything before Claude scores, and everything after |
| `uv run sources.py test` | Run every adapter against its saved responses, offline |
| `uv run sources.py try <source.json> [out.json]` | Run one source live and show a sample |
| `uv run sources.py fetch <config.json>` | Fetch every enabled source into `work/fetched/` |
| `uv run sources.py domains <config.json>` | List the domains the enabled sources need |
| `uv run engine.py prepare <config.json>` | Collect, filter and prepare `work/batch.json` |
| `uv run engine.py finish <config.json>` | Check judgments, rank, write `work/results.json` |
| `uv run dbio.py config` / `export` | Convert between the artifact's database and these files (used by the cloud run) |

## Sources and adapters

Built in adapters: Greenhouse, Lever, Ashby, Workable, Getro (venture firm portfolio boards), JSON API, web page (CSS selectors), RSS. Two more types exist only as sources: the frozen corpus of 20 fictional postings for repeatable tests, and "check by hand" reminders for boards that block automated access.

**Starting sources.** A new Job Agent artifact starts with the boards in `defaults/agent.json`: company boards in AI, crypto and fintech, venture firm portfolio boards, and a few check-by-hand reminders for sites without a public feed. Turn off the ones that don't fit your search on the Sources tab. To change what every new artifact starts with, edit that file.

**When a source breaks**, the fix is usually in its settings, not code: new selectors for a web page, new field paths for a JSON API, a corrected board token. The artifact flags sources that fail or suddenly return nothing, and the daily run proposes fixes it has tested. You apply or discard them.

**To add an adapter type**, add a file in `adapters/` with a class that subclasses `BaseSource` and implements `fetch()` and `normalize()`, register it in `adapters/__init__.py`, and add a fixture in `adapters/fixtures/` so `sources.py test` covers it. The existing adapters are short and make good templates. In the artifact, a custom adapter can also be written as code for a single source.

**Requests go only to a source's own domains.** The code checks this. In the cloud, the environment's network setting is the real limit.

## Limits

Course limits live in `caps.json` and are enforced in code: the morning run always runs and you may start ten more a day by hand (a rolling 24 hours), three active searches, 1,000 postings read per source, 10,000 per run, 12 judged per search. Reading is cheap and done in code, so every fetched posting goes through your filters and the ranking; judging is what uses your plan, so that is the tight cap. The artifact can lower them, never raise them.

## Your data

- Your CV file never leaves your computer. The artifact extracts its text in your browser, you edit what the agent may read, and only that text is saved.
- Searches, matches, verdicts, run records and the latest day's collected postings live in the Job Agent artifact's database on Claude's servers, readable only by you. Nothing personal goes into this repository; `work/` is ignored by git.

## Known limits

- Getro boards list jobs without descriptions, and web page sources read only the listing unless a description selector is set; expect more unknown scores from these.
- Which postings get scored is decided by a cheap prefilter: your search's keywords (a keyword in the title counts double), plus word overlap with your CV. It decides what the agent sees, so choose keywords with care.
- Your verdicts drive the Agent tab's Feedback: agreement compares them with the agent's scores per version, and suggested changes propose edits to your Profile. Nothing changes until you apply it. Agreement is a signal from your own verdicts, not a fixed test set: each version is judged on different posts.

## Files

```
week7-job-agent/
├── README.md            this file
├── RUN.md               what the cloud run follows, step by step
├── SETUP.md             what Claude follows to set up a Job Agent page and daily run
├── GUIDE.md             the guide: daily use, changing the agent, an exercise
├── console.html         the Job Agent page
├── engine.py            collect, filter, prepare, check, rank
├── sources.py           run sources through adapters
├── dbio.py              page database <-> local files
├── adapters/            one file per adapter type, plus fixtures/
├── corpus/postings.jsonl  20 fictional postings for repeatable tests
├── examples/            a sample config and a sample source
├── defaults/            starting agent settings and first search for a new page
├── caps.json            course limits
└── pyproject.toml, uv.lock
```
