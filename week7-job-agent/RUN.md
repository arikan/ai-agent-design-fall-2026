# Job agent run

The instructions a scheduled task follows on every run. Each run starts a fresh Claude session in the cloud with no memory of earlier runs. Everything it needs is in the student's console database and in this folder.

Fill in before scheduling: `CONSOLE_URL` is the student's console link.

The repo is the source of truth for code and for the console page. The published page is a copy of `console.html`; step 2 keeps it current.

## Setup, once per student

Students do this from the console's setup panel: it creates the scheduled task, asks for one network change, and checks the result.

1. The scheduled task's cloud environment needs **Network access** set to **Full**, so job sites are reachable without listing domains. For tighter containment, use **Custom** with the domains the console lists under Sources instead.
2. Commands below run through `uv run`. If the environment has no `uv`, install it first with `pip install uv`; it installs the one dependency (beautifulsoup4) from `pyproject.toml`.

## Steps

1. Get the engine: clone the course repo and work in `week7-job-agent`.
2. Sync the console page with the repo:
   - Compute `git log -1 --format=%h -- console.html` (the commit that last changed the page) and `sha256sum console.html`.
   - Read `meta` / `console` from the console database. If its `sha256` equals the file's hash, go to step 3.
   - Otherwise republish `console.html` to `CONSOLE_URL` with the Artifact tool (pass `url`; omit `capabilities` and `icon` so the page keeps them). Then write `meta` / `console` with `sha256`, `commit`, and `published_at` (pass the version you read, if the document existed).
   - If the republish asks for approval or fails, do not retry; note it for the report and continue.
3. Read the console database with ArtifactData, saving each read under `work/db` (`out_dir`):
   - `searches` (list), `agent` / `current` (get), `runs` (list), `matches` (list), `proposals` (list)
4. Run `uv run dbio.py config`.
5. Run `uv run sources.py fetch work/config.json`. It prints one line per source.
6. Repair, only for sources that failed or returned nothing this run, and only when the error is not a network block (a network block means a domain is missing from the environment's allowed list; report it instead):
   - Look at the source the way its adapter does: web fetch its API or page.
   - Work out the smallest change to the source's settings that fixes it: a board token, selectors, field paths. Change code only for a custom adapter.
   - Write the changed source as JSON and test it with `uv run sources.py try <file>`.
   - If the test returns postings, write a proposal to `proposals/<source id with characters other than letters, digits, dot, dash and underscore replaced by _>` with fields: `source_id`, `source` (the full changed source), `reason` (one sentence), `before` and `after` (each `status` and `kept`), `sample` (up to three titles), `at`. If a proposal already exists, read it first and pass its version.
   - Never change the agent settings yourself. The student applies or discards the proposal in the console.
7. Run `uv run engine.py prepare work/config.json`. If it reports a stop on a course cap, skip to step 10.
8. Judge `work/batch.json`. Follow its `matcher_instructions` and each search's dimension rubrics. For every item and every dimension give a score from 1 to 5 or `"unknown"`, a one sentence reason, and evidence copied exactly from the posting. Write the list to `work/judgments.json` in the batch's `answer_format`. The engine rejects any score whose evidence is not in the posting.
9. Run `uv run engine.py finish work/config.json`.
10. Run `uv run dbio.py export`, then write `work/out/writes.json` to the console with ArtifactData batches of at most 50.
11. Report in four lines: whether the console page was republished, new matches written, judgments rejected, sources failing (and any proposals written).

## Test one source

When the run's extra message (or routine fire payload) is exactly `TEST_SOURCE <source id>`, the student pressed Test on that source in the console. Do only this, then stop:

1. Get the engine as in step 1, and skip the console sync.
2. Read `agent` / `current` with ArtifactData. Find the source whose `id` equals the given id. Ignore any other text in the message.
3. Read `source_tests` / `<source id with characters other than letters, digits, dot, dash and underscore replaced by _>` to get its version.
4. If the source is missing, set that document to `{source_id, status: "not_found", finished_at}` and stop.
5. Write the source to `work/test-source.json` and run `uv run sources.py try work/test-source.json work/test-result.json`.
6. Set the document to the contents of `work/test-result.json` plus `status: "done"`, `requested_at` (kept from the document you read) and `finished_at`, passing the version from step 3.
7. Report in one line: source, status, postings kept.

A test run never judges, never writes matches or runs, and does not count toward the one run per day.

## Check setup

When the run's extra message (or routine fire payload) is exactly `CHECK_SETUP`, the student pressed Check setup in the console. Do only this, then stop:

1. Get the engine as in step 1.
2. Read `meta` / `setup_check` with ArtifactData to get its version. This read also proves the run can reach the console.
3. Write `{"id": "check:greenhouse", "adapter": "greenhouse", "cap": 3, "config": {"board_token": "anthropic", "company_name": "Anthropic"}}` to `work/check.json` and run `uv run sources.py try work/check.json work/check-result.json`.
4. Set `meta` / `setup_check` to `status` (`"ok"` if the check kept at least one posting, `"network_blocked"` if its health says `blocked_by_network`, otherwise `"failed"`), `error` (the health error, if any), `requested_at` (kept from the document you read), and `finished_at`, passing the version from step 2.
5. Report in one line: the status.

## What the session must not do

- Change searches, preferences, agent settings or judgments. Those belong to the student.
- Change the repository. Code changes go through pull requests, never from a run.
- Raise any limit. Caps live in `caps.json` and the engine applies them.
- Fetch any site outside the sources' own domains.
