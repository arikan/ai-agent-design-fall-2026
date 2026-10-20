# Set up a Job Agent

Instructions for a Claude Code session. Anyone can start it by sending:

> Set up my Job Agent by following https://github.com/arikan/ai-agent-design-fall-2026/blob/main/week7-job-agent/SETUP.md

At the end the user has their own Job Agent artifact, a daily scheduled task that runs their agent, and the two connected. Work in this session's cloud environment; the scheduled task uses the same one.

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

Reply briefly, in this order:

1. The link to their Job Agent artifact.
2. One setting to change, here in this session: click the arrow after this session's title at the top, choose **Edit cloud environment**, set **Network access** to **Full**, and save. Their daily run uses this same environment and needs it to reach job sites.
3. Then, in their artifact, press **I've changed it, check my setup**. When it turns green, **Start my agent** runs it right away.

## Do not

- Run the agent, test sources, or fire the scheduled task. The user does that from their artifact.
- Change anything in the repository.
- Put the user's answers anywhere except their own artifact's database.
