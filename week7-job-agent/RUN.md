# Job agent run

The instructions a scheduled task follows on every run. Each run starts a fresh Claude session in the cloud with no memory of earlier runs. Everything it needs is in the student's console database and in this folder.

Fill in before scheduling: `CONSOLE_URL` is the student's console link.

The repo is the source of truth for code and for the console page. The published page is a copy of `console.html`; step 9 keeps it current.

## Setup, once per student

Students do this from the console's setup panel: it creates the scheduled task, asks for one network change, and checks the result.

1. The scheduled task's cloud environment needs **Network access** set to **Full**, so job sites are reachable without listing domains. For tighter containment, use **Custom** with the domains the console lists under Sources instead.
2. Commands below run through `uv run`. If the environment has no `uv`, install it first with `pip install uv`; it installs the one dependency (beautifulsoup4) from `pyproject.toml`.

## Steps

A run should take few turns: do independent tool calls in the same turn, and never read the files under `work/db` or `work/out` into the conversation; pass them by path. The page shows progress from `meta` / `progress`.

1. **Decide what this run is.** Read `meta` / `request` with ArtifactData. If it exists, its `status` is `"pending"`, and its `requested_at` is less than 30 minutes old:
   - `kind: "check"`: follow "Check setup" below instead of these steps.
   - `kind: "test"`: follow "Test one source" below for its `source_id`.
   - `kind: "run"`: the student asked for a run now; continue.
   Set its `status` to `"started"` (pass the version you read). Otherwise this is the daily run; continue. An extra message `TEST_SOURCE <id>` or `CHECK_SETUP` means the same as a request of that kind.
2. **Get the engine.** In one command: shallow clone the course repo, `cd` into `week7-job-agent`, and run `pip install -q uv` if `uv` is missing.
3. **Read the database**, all in one turn, each with `out_dir: work/db`: `searches` (list), `agent` / `current` (get), `runs` (list), `matches` (list), `meta` / `progress`, `meta` / `console` and `meta` / `postings` (get; any may not exist).
4. **Collect, filter and rank:** `uv run run.py prepare`, or `uv run run.py prepare manual` when step 1 found a `run` request (the student pressed Run now; those runs are capped at a few a day, the morning run is not). It prints how long each stage took.
   - If it says the run stopped on the course cap, go to step 7.
   - Otherwise set `meta` / `progress` from `work/out/progress.json` (`file_path`, with the version from step 3; keep the version the write returns).
5. **Judge** `work/batch.json`: follow its `matcher_instructions` and each search's dimension rubrics. For every item and every dimension give a score from 1 to 5 or `"unknown"`, a one sentence reason, and evidence copied exactly from the posting's `text`. Keep reasons short. Write the list to `work/judgments.json` in the batch's `answer_format`, in one file write. The engine rejects any score whose evidence is not in the text.
6. **Rank and package:** `uv run run.py finish --model <id>`, where `<id>` is the model you are running as, exactly as your system prompt names it (for example `claude-sonnet-4-5`). It is recorded on the run and on every match, so a score can always be traced to the model that gave it. The command also reads this session's token usage from its transcript and records it on the run.
7. **Write back**, in one turn:
   - `work/out/writes.json` with ArtifactData `batch` (at most 50 writes per call; each entry already has its `file_path`)
   - `meta` / `progress` from `work/out/progress.json` (with the version you kept)
   - `meta` / `postings` from `work/out/postings-index.json`, if that file exists (with the version from step 3): it points the page at the day's collected postings, which `writes.json` already carried
   - if this run came from a request, `meta` / `request` `status` `"done"`
8. **Repair** (skip when every source in the fetch output is `ok`, or the failure is a network block, which you report instead): for a source that failed or returned nothing, look at its API or page with a web fetch, work out the smallest settings change that fixes it (board token, selectors, field paths; code only for a custom adapter), write it as JSON under `work/` (which git ignores, so the run leaves the repository clean) and test it with `uv run sources.py try <file>`. If it returns postings, write a proposal to `proposals/<source id with characters other than letters, digits, dot, dash and underscore replaced by _>` with `source_id`, `source` (the full changed source), `reason` (one sentence), `before` and `after` (each `status` and `kept`), `sample` (up to three titles), `at`. Never change the agent settings yourself.
9. **Sync the page** (last, so matches appear first): if `sha256sum console.html` differs from the `sha256` in `meta` / `console` (read in step 3), republish `console.html` to `CONSOLE_URL` with the Artifact tool (pass `url`; omit `capabilities` and `icon`), then write `meta` / `console` with `sha256`, `commit` (`git log -1 --format=%h -- console.html`) and `published_at`. If the republish asks for approval or fails, skip it.
10. **Report** in four lines: stage times from steps 4 and 6, new matches, judgments rejected, sources failing (and proposals written).

## Test one source

When step 0 finds a pending `test` request, the student pressed Test on that source. Do only this, then stop:

1. Get the engine as in step 2.
2. Read `agent` / `current` with ArtifactData. Find the source whose `id` equals the request's `source_id`.
3. Read `source_tests` / `<source id with characters other than letters, digits, dot, dash and underscore replaced by _>` to get its version.
4. If the source is missing, set that document to `{source_id, status: "not_found", finished_at}` and stop.
5. Write the source to `work/test-source.json` and run `uv run sources.py try work/test-source.json work/test-result.json`.
6. Set the document to the contents of `work/test-result.json` plus `status: "done"`, `requested_at` (kept from the document you read) and `finished_at`, passing the version from step 3.
7. Set `meta` / `request` `status` to `"done"` and report in one line: source, status, postings kept.

A test run never judges, never writes matches or runs, and does not count toward the one run per day.

## Check setup

When step 0 finds a pending `check` request, the student pressed Check setup. Do only this, then stop:

1. Get the engine as in step 2.
2. Read `meta` / `setup_check` with ArtifactData to get its version. This read also proves the run can reach the console.
3. Write `{"id": "check:greenhouse", "adapter": "greenhouse", "cap": 3, "config": {"board_token": "anthropic", "company_name": "Anthropic"}}` to `work/check.json` and run `uv run sources.py try work/check.json work/check-result.json`.
4. Set `meta` / `setup_check` to `status` (`"ok"` if the check kept at least one posting, `"network_blocked"` if its health says `blocked_by_network`, otherwise `"failed"`), `error` (the health error, if any), `requested_at` (kept from the document you read), and `finished_at`, passing the version from step 2.
5. Set `meta` / `request` `status` to `"done"` and report in one line: the status.

## What the session must not do

- Change searches, preferences, agent settings or judgments. Those belong to the student.
- Change the repository. Code changes go through pull requests, never from a run.
- Raise any limit. Caps live in `caps.json` and the engine applies them.
- Fetch any site outside the sources' own domains.
