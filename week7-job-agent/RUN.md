# Job agent run

The instructions a scheduled task follows on every run. Each run starts a fresh Claude session in the cloud with no memory of earlier runs. Everything it needs is in the user's Job Agent artifact's database and in this folder.

Fill in before scheduling: `CONSOLE_URL` is the link to the user's Job Agent artifact.

The repo is the source of truth for code and for the Job Agent artifact. The published artifact is a copy of `console.html`; step 9 keeps it current.

## Setup, once

Done once from the artifact's setup panel: it creates the scheduled task, asks for one network change, and checks the result.

1. The scheduled task's cloud environment needs **Network access** set to **Full**, so job sites are reachable without listing domains. For tighter containment, use **Custom** with the domains the artifact lists under Sources instead.
2. Commands below run through `uv run`. If the environment has no `uv`, install it first with `pip install uv`; it installs the one dependency (beautifulsoup4) from `pyproject.toml`.

## Steps

If any step fails and you stop early, first set `meta` / `request` `status` to `"done"` with `ended`: one plain sentence of what failed, and `session_url` (this session's page, as in "Check setup"). The artifact shows it; without it, the person waits for a result that never comes.

A run should take few turns: do independent tool calls in the same turn, and never read the files under `work/db` or `work/out` into the conversation; pass them by path. The artifact shows progress from `meta` / `progress`.

1. **Decide what this run is.** Read `meta` / `request` with ArtifactData. If it exists, its `status` is `"pending"`, and its `requested_at` is less than 30 minutes old:
   - `kind: "check"`: follow "Check setup" below instead of these steps.
   - `kind: "test"`: follow "Test one source" below for its `source_id`.
   - `kind: "suggest"`: follow "Suggest changes" below.
   - `kind: "figure"`: follow "Figure out a source" below for its `url`, the page's address.
   - `kind: "find"`: follow "Find a board by name" below for its `name`, a company name.
   - `kind: "run"`: the user asked for a run now; continue.
   Set its `status` to `"started"` (pass the version you read). Otherwise this is the daily run; continue. An extra message `TEST_SOURCE <id>`, `FIGURE_SOURCE <url>`, `FIND_SOURCE <name>` or `CHECK_SETUP` means the same as a request of that kind.
2. **Get the engine.** In one command: shallow clone the course repo, `cd` into `week7-job-agent`, and run `pip install -q uv` if `uv` is missing.
3. **Read the database**, all in one turn, each with `out_dir: work/db`: `searches` (list), `agent` / `current` (get), `runs` (list), `matches` (list), `judgments` (list), `rescore` (list; postings the user asked to score again), `meta` / `progress`, `meta` / `console` and `meta` / `postings` (get; any may not exist).
4. **Collect, filter and rank:** `uv run jobagent prepare`, or `uv run jobagent prepare manual` when step 1 found a `run` request (the user pressed Run now; those runs are capped at a few a day, the morning run is not). It prints how long each stage took.
   - If it says the run stopped on the course cap, go to step 7.
   - Otherwise set `meta` / `progress` from `work/out/progress.json` (`file_path`, with the version from step 3; keep the version the write returns).
5. **Judge** `work/batch.json`: follow its `matcher_instructions` and each search's dimension rubrics. For every item and every dimension give a score from 1 to 5 or `"unknown"`, a one sentence reason, and evidence copied exactly from the posting's `text`. Keep reasons short. Write the list to `work/judgments.json` in the batch's `answer_format`, in one file write. The engine rejects any score whose evidence is not in the text.
6. **Rank and package:** `uv run jobagent finish --model <id>`, where `<id>` is the model you are running as, exactly as your system prompt names it (for example `claude-sonnet-4-5`). It is recorded on the run and on every match, so a score can always be traced to the model that gave it. The command also reads this session's token usage from its transcript and records it on the run.
7. **Write back**, in one turn:
   - `work/out/writes.json` with ArtifactData `batch` (at most 50 writes per call; pass each entry as it is, with its `file_path` and, for a rescored match or a cleared rescore request, its `if_version`)
   - `meta` / `progress` from `work/out/progress.json` (with the version you kept)
   - `meta` / `postings` from `work/out/postings-index.json`, if that file exists (with the version from step 3): it points the artifact at the day's collected postings, which `writes.json` already carried
   - if this run came from a request, `meta` / `request` `status` `"done"`
8. **Repair** (skip when every source in the fetch output is `ok`, or the failure is a network block, which you report instead): for a source that failed or returned nothing, look at its API or page with a web fetch, work out the smallest settings change that fixes it (board token, selectors, field paths; code only for a custom adapter), write it as JSON under `work/` (which git ignores, so the run leaves the repository clean) and test it with `uv run jobagent sources try <file>`. If it returns postings, write a proposal to the artifact's database with ArtifactData (not a file): collection `proposals`, document id `<source id with characters other than letters, digits, dot, dash and underscore replaced by _>`, with `source_id`, `source` (the full changed source), `reason` (one sentence), `before` and `after` (each `status` and `kept`), `sample` (up to three titles), `at`. Never change the agent settings yourself.
9. **Sync the artifact** (last, so matches appear first): if `sha256sum console.html` differs from the `sha256` in `meta` / `console` (read in step 3), republish `console.html` to `CONSOLE_URL` with the Artifact tool (pass `url`; omit `capabilities` and `icon`), then write `meta` / `console` with `sha256`, `commit` (`git log -1 --format=%h -- console.html`) and `published_at`. If the republish asks for approval or fails, skip it.
10. **Suggest**, only if `agent` / `current` has `settings.suggest_after_run` set to true: do steps 3 to 5 of "Suggest changes" (the database is already read).
11. **Report** in four lines: stage times from steps 4 and 6, new matches, judgments rejected, sources failing (and proposals written).

## Suggest changes

When step 1 finds a pending `suggest` request, the user asked for suggestions. Do only this, then stop:

1. Get the engine as in step 2.
2. Read, in one turn, each with `out_dir: work/db`: `searches` (list), `agent` / `current` (get), `matches` (list), `judgments` (list), `runs` (list).
3. `uv run jobagent suggest prepare`. If it says there is nothing to suggest, skip to step 6.
4. Read `work/suggest.json` and follow its `instructions`: propose changes to the user's Profile that would make the agent's scores agree better with their Good and Nope verdicts. Write `work/suggestions.json` in its `answer_format`, in one file write. These are proposals only; never change a search yourself.
5. `uv run jobagent suggest finish --model <id>` (your model, as in step 6 above). Write `work/out/suggestion.json` with ArtifactData `set` to collection `suggestions` under the document id it prints.
6. Set `meta` / `request` `status` to `"done"` and report in one line: suggestions written and rejected.

A suggestion request never collects or scores posts, and does not count toward the runs started by hand.

## Figure out a source

When step 1 finds a pending `figure` request, the user pasted a careers page address the agent doesn't know. Work out how to read it, then stop:

1. Get the engine as in step 2. Read `agent` / `current` and `meta` / `figure` with ArtifactData, for their versions.
2. Set `meta` / `figure` to `{"url": <the address>, "status": "working", "started_at": now}`.
3. Run `uv run jobagent figure <url> --model none`. It opens the page, and either finds a board it knows (an embedded Greenhouse, Lever, Ashby or Workable board, or an RSS feed) and tests it, or writes the page's HTML, without scripts, to `work/figure-page.html` for you. Read `work/figure-result.json`.
4. If it found a source, go to step 7. If it says the page can't be read (empty without JavaScript, or it couldn't open it), go to step 8.
5. You are the model now. Read `work/figure-page.html` and write one source to `work/figure-source.json`: `{"id": "html:<host>", "adapter": "html_scraper", "enabled": true, "category": "", "cap": 1000, "note": "<what the page is, one line>", "config": {"url": <the address>, "selectors": {"job_card": <css>, "title": <css>, "location": <css or omit>, "company": <css or omit>, "link": <css, default a>}, "detail_text": <css on a job's own page for its description, or omit>, "company_name": "<name>"}}`. The selectors are CSS for BeautifulSoup; `job_card` matches one element per job and the others are searched inside it. If the page only links to the real job list (a careers landing page), don't follow it: put that link in `meta` / `figure` as `follow` in step 8, so the user can add it with one click. If the HTML holds no job listings (they load with JavaScript, or the page is a search form), say so and go to step 8.
6. Test it: `uv run jobagent sources try work/figure-source.json work/figure-test.json`. If it kept no postings, read the error and the page again and fix the selectors, up to three times in all. If the page's HTML or its network responses show a JSON API that lists the jobs, a `json_api` source for that API is better than selectors.
7. If the address searches for one of the person's target roles (for example `?search=Head+of+Product`), add `url_template` to the source's `config`: the same address with `{role}` in place of that role. Each run then searches it once for every target role in the profile. Then, if a source with the same `id` is already in `agent` / `current`'s `sources`, don't add it: in step 8 set `already` to that id and `source` to null. Otherwise add the source: write `agent` / `current` with the source appended to `sources` and `version` raised by one (pass the version from step 1), and `agent/current/versions` / `v<new version>` with the same document plus `note` "Added <source id> from <url>". Write `source_tests` / `<source id with characters other than letters, digits, dot, dash and underscore replaced by _>` from `work/figure-test.json` (or a `{"health": {"status": "ok", "kept": N}}` for a source found by code) plus `source_id`, `status: "done"`, `finished_at`.
8. Set `meta` / `figure` to `{"url", "status": "done", "source": <the source, or null>, "how": "<one plain sentence: what was found and how, or why the page can't be read and where its jobs come from>", "finished_at"}`, with the version from step 2. Set `meta` / `request` `status` to `"done"` and report in one line.

This is the one case where a run changes the agent's sources: the user asked for exactly that address.

## Find a board by name

When step 1 finds a pending `find` request, the user typed a company name. Find its job board and add it, then stop:

1. Get the engine as in step 2. Read `agent` / `current` and `meta` / `figure` with ArtifactData, for their versions.
2. Set `meta` / `figure` to `{"url": "name:<the name>", "status": "working", "started_at": now}`. Use exactly that `url` in every later write to `meta` / `figure`; the artifact waits for it.
3. Run `uv run jobagent find "<the name>" --model none`. It tries the company's Greenhouse, Lever, Ashby and Workable boards by name, then likely careers addresses on its own site, looking for an embedded board or a feed, and tests what it finds. Read `work/find-result.json`.
4. If it found a source, write it to `work/figure-test.json` as `{"health": {"status": "ok"}}` and do steps 7 and 8 of "Figure out a source", with the source from `work/find-result.json`, the note "Added <source id> for <the name>", and a `how` from its `how`. Set the source's `about` to what the company does, a few words, and `category` to one or two words, if you know them.
5. Otherwise search the web for the company's careers or jobs page (for example "<the name> careers"). The board is often on a host named in the page (Greenhouse, Lever, Ashby, Workable): if so, run `uv run jobagent find "<that board's company slug>" --model none` or add that board as in step 4. Else take the page that lists the jobs and do "Figure out a source" from its step 3 with that address, keeping `url` "name:<the name>" in `meta` / `figure`.
6. If nothing works, set `meta` / `figure` to `{"url": "name:<the name>", "status": "done", "source": null, "how": "<one plain sentence: what you tried and, if you found it, the careers page address>", "page": <that address or null>, "finished_at"}`, set `meta` / `request` `status` to `"done"` and report in one line.

## Test one source

When step 0 finds a pending `test` request, the user pressed Test on that source. Do only this, then stop:

1. Get the engine as in step 2.
2. Read `agent` / `current` with ArtifactData, and `searches` (list) with `out_dir: work/db` (a source that searches by target role needs them). Find the source whose `id` equals the request's `source_id`.
3. Read `source_tests` / `<source id with characters other than letters, digits, dot, dash and underscore replaced by _>` to get its version.
4. If the source is missing, set that document to `{source_id, status: "not_found", finished_at}` and stop.
5. Write the source to `work/test-source.json` and run `uv run jobagent sources try work/test-source.json work/test-result.json`.
6. Set the document to the contents of `work/test-result.json` plus `status: "done"`, `requested_at` (kept from the document you read) and `finished_at`, passing the version from step 3.
7. Set `meta` / `request` `status` to `"done"` and report in one line: source, status, postings kept.

A test run never judges, never writes matches or runs, and does not count toward the one run per day.

## Check setup

When step 0 finds a pending `check` request, the user pressed Check setup. Do only this, then stop:

1. Get the engine as in step 2.
2. Read `meta` / `setup_check` with ArtifactData to get its version. This read also proves the run can reach the artifact.
3. Write `{"id": "check:greenhouse", "adapter": "greenhouse", "cap": 3, "config": {"board_token": "anthropic", "company_name": "Anthropic"}}` to `work/check.json` and run `uv run jobagent sources try work/check.json work/check-result.json`.
4. Set `meta` / `setup_check` to `status` (`"ok"` if the check kept at least one posting, `"network_blocked"` if its health says `blocked_by_network`, otherwise `"failed"`), `error` (the health error, if any), `session_url` (this session's page: `https://claude.ai/code/session_<X>` where the environment variable `CLAUDE_CODE_REMOTE_SESSION_ID` is `cse_<X>`), `requested_at` (kept from the document you read), and `finished_at`, passing the version from step 2.
5. Set `meta` / `request` `status` to `"done"` and report in one line: the status.

## What the session must not do

- Change searches, preferences, agent settings or judgments. Those belong to the user; suggestions are written for the user to apply or not. The one exception is "Figure out a source", which adds the source the user asked for.
- Change the repository. Code changes go through pull requests, never from a run.
- Raise any limit. Caps live in `caps.json` and the engine applies them.
- Fetch any site outside the sources' own domains.
