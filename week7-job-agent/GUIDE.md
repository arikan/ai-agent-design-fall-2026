# Your Job Agent: a student guide

Your Job Agent reads job boards every morning, keeps the posts that fit your profile, and asks a model to score the best few. You judge the results. Over a week, your judgments show how good the agent is and what to change.

## 1. Set it up (15 minutes, once)

Follow [Start here](README.md#start-here). You need a paid Claude plan.

The step people miss: in the setup session, set **Network access** to **Full**. Without it, the agent can't reach job sites and the setup check stays red.

## 2. Use it every day (5 minutes)

1. Open your Job Agent page. New posts are under **Matches**, **To review**.
2. Mark each one **Good** or **Nope**, and pick the main reason.
3. Read one post's score explanation (click its scores) and ask: would I have scored it that way?

Judge at least 5 posts a day. The agent can't be measured, or improved, without your judgments.

## 3. What each tab is for

| Tab | What it shows |
|---|---|
| Matches | Posts the model scored, with a reason and a quote for each score |
| Profile | What you want: roles, industries, pay, CV, filters, and the dimensions posts are scored on |
| Sources | The job boards the agent reads |
| Agent | How the agent works, how well it agrees with you, and its settings |
| Runs | What each run did: posts collected, dropped and why, cost |

Only one step uses a model. Everything else is code you can read in this folder.

## 4. Three exercises

Write a few lines for each.

1. **Trace one match.** Pick a post in Matches. Find which board it came from, why it passed the filters, and what the model read before scoring it (Runs, and Agent → What the model sees). Did the model have what it needed?
2. **Name a failure.** Find a post the agent got wrong: a good job scored low, a bad one scored high, or a good job that never appeared. Say where it went wrong: the board's data, a filter, the ranking, your rubric, or the model.
3. **Make one measured change.** Note your agreement number under Agent → Evaluation. Make one change, or apply one suggestion. Judge at least 5 new posts. Did agreement go up? Is that enough posts to tell?

## 5. Make it yours

- **On the page, no code:** change your profile, rubrics and weights; add boards; apply suggestions. Each change is saved as a version, so you can compare.
- **The model's instructions:** edit Agent → Settings → Scoring instructions. Same idea: change, judge, compare.
- **The code:** fork the repository and point your daily run at your fork. See [Make it yours](README.md#make-it-yours).

## Good to know

- Your CV text and judgments are stored on your page, visible only to you.
- Each run uses your Claude plan. You can start up to 10 runs a day by hand; the morning run is extra.
- Some boards give little to read. Posts from portfolio boards (Getro) have no description, so many scores come back "unknown".
