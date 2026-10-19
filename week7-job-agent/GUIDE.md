# Your Job Agent: a student guide

Your Job Agent reads job boards every morning, keeps the posts that fit your profile, and asks a model to score the best few. You judge the results. Over a week, your judgments show how good the agent is, and the agent suggests what to change.

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

## 4. Make it yours

- **On the page, no code:** change your profile, rubrics and weights; add boards; apply suggestions. Each change is saved as a version, so you can compare.
- **The model's instructions:** edit Agent → Settings → Scoring instructions. Same idea: change, judge, compare.
- **The code:** fork the repository and point your daily run at your fork. See [Make it yours](README.md#make-it-yours).

## 5. Exercise: improve your agent with its suggestions

1. **Judge at least 10 posts**, with both Good and Nope among them. Under Agent → Evaluation, write down your agreement.
2. **Press Suggest changes.** The model reads where you and the agent disagree and proposes up to three changes to your profile. Apply the ones you agree with and dismiss the rest. Write one line on each: why you applied or dismissed it.
3. **Run again** (Run now, or wait for the morning run), then **judge at least 5 new posts**, again with both Good and Nope.
4. **Compare.** "By version" shows agreement for the posts scored before and after your change. Did it go up? Is that enough posts to tell?

Write a few lines: what you applied, what you dismissed, agreement before and after, and one thing the suggestions missed.

## Good to know

- Your CV text and judgments are stored on your page, visible only to you.
- Each run uses your Claude plan. You can start up to 10 runs a day by hand; the morning run is extra.
- Some boards give little to read. Posts from portfolio boards (Getro) have no description, so many scores come back "unknown".
