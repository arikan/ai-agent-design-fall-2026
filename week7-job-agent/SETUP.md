# Set up a Job Agent

Instructions for a Claude Code session. Anyone can start it by sending:

> Set up my Job Agent by following https://github.com/arikan/ai-agent-design-fall-2026/blob/main/week7-job-agent/SETUP.md

At the end the user has their own Job Agent artifact, a daily scheduled task that runs their agent, and the two connected. The scheduled task runs in this session's cloud environment, so this session must be able to reach job boards before anything is created.

## 0. Check the network first

Run `curl -sS -o /dev/null -w "%{http_code}" https://boards-api.greenhouse.io/v1/boards/anthropic/jobs`.

If it prints `200`, continue to step 1. Otherwise (a `403`, "Tunnel connection failed", or a connection error) this environment's network access is limited, and a task created from it would fail the same way. Create nothing. Reply with exactly this, and stop:

> Before I set anything up, your cloud environment needs to be able to reach job boards. Right now it can't. Do this, then start a new session and send me the setup message again:
> 1. Open https://claude.ai/code. You land on the new session screen. Don't type anything yet.
> 2. Under the message box there is a row of small buttons. The first one shows your environment's name, usually **Default**. Click it.
> 3. Hover over **Default** in the list and click the settings icon that appears on its right.
> 4. Set **Network access** to **Full** and save.
> Then start the new session from that same screen, so it uses the environment you just changed.

## 1. Ask one question

Ask the user, in one message:

> Which roles are you looking for, which industries would you like to work in, and what's your background in a few keywords? For example: "Head of Product, VP of Product; fintech, AI; 8 years in product, B2B SaaS, design systems". Also, where are you based, so the daily run happens in your morning? Skip anything you like; I'll use sensible defaults and you can change everything later in your artifact.

Turn the roles into `target_roles`, the industries into `industries`, and the background into `keywords` (comma separated lists). Use their time zone for the schedule, or `America/New_York` if they skip it.

## 2. Get the files

Shallow clone https://github.com/arikan/ai-agent-design-fall-2026 and work in `week7-job-agent`. Do not commit or push anything.

## 3. Publish the artifact

Publish `console.html` with the Artifact tool as a new artifact:

- title `Job Agent`, icon `briefcase`, description `Find jobs that fit you, every day.`
- capabilities, exactly:
  `{"db": {"rules": [{"path": "", "read": "owner", "write": "owner"}]}, "mcp": {"servers": [{"server": "Claude Code Remote", "tools": ["list_triggers", "fire_trigger"]}]}}`

The `owner` rule keeps the database private to the user, including their CV text. Note the new artifact's URL; below it is `ARTIFACT_URL`.

## 4. Seed the artifact's database

Write these with one ArtifactData batch to `ARTIFACT_URL`, using the current time for every timestamp:

- `meta` / `app`: `{"console_url": ARTIFACT_URL}`
- `agent` / `current`: the contents of `defaults/agent.json`, plus `updated`
- `agent/current/versions` / `v1`: `{"version": 1, "note": "Starting settings", "updated": ...}`
- `searches` / `my-first-search`: the contents of `defaults/search.json`, with `target_roles`, `keywords` and `industries` replaced by the user's answers when given, plus `updated`
- `meta` / `setup_check`: `{"status": "ok", "via": "setup", "requested_at": ..., "finished_at": ...}`. Step 0 already proved this environment reaches job boards, and the task runs in the same environment, so the artifact starts ready.

## 5. Create the daily run

Create a scheduled task in this session's environment:

- name: `Job agent daily run`
- schedule: every day at 7:47 AM in the user's time zone
- prompt, exactly, with `ARTIFACT_URL` filled in:

```text
You run a person's job agent. Clone https://github.com/arikan/ai-agent-design-fall-2026 (a shallow clone is enough) and work in its week7-job-agent folder. Follow week7-job-agent/RUN.md exactly, starting at "Steps".
CONSOLE_URL is ARTIFACT_URL
If this run includes a message or fire payload of the exact form "TEST_SOURCE <source id>" or "CHECK_SETUP", follow the matching section of RUN.md ("Test one source" or "Check setup") instead of "Steps".
Do not commit or push anything. If a step fails, stop, and report which step failed and the error, in two lines.
```

Then write `meta` / `agent` to `ARTIFACT_URL`: `{"trigger_id": <the new task's id>, "name": "Job agent daily run", "connected_at": ...}`. This connects the artifact to the task.

## 6. Tell the user what's next

Reply briefly:

1. The link to their Job Agent artifact.
2. Their agent runs every morning. In the artifact, **Start my agent** runs it right away; first matches appear in a few minutes.

## Do not

- Run the agent, test sources, or fire the scheduled task. The user does that from their artifact. The curl in step 0 is the only request to a job site you make.
- Change anything in the repository.
- Put the user's answers anywhere except their own artifact's database.
