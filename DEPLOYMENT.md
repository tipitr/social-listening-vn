# Deployment Guide — Social Listening VN

This is a one-time setup. After it's done, the team can use the dashboard
forever and never touch this file again.

**Total time:** about 1 hour, mostly waiting for sign-ups.

**You'll create accounts on three services (all free for our usage):**

1. **Supabase** — hosts the database
2. **GitHub** — hosts the code and runs the daily scrape
3. **Streamlit Cloud** — hosts the dashboard the team opens in their browser

---

## Step 1 — Push the code to GitHub

If the project isn't already on GitHub:

```bash
cd /path/to/social-listening-vn
git init
git add .
git commit -m "Initial commit"
```

Then on https://github.com → **New repository** → name it `social-listening-vn`
(private is fine) → follow the "push existing repo" instructions GitHub shows.

> **Don't worry about secrets leaking.** `.gitignore` already excludes `.env`,
> `data/`, and `.streamlit/secrets.toml` — none of your keys go up.

---

## Step 2 — Create a Supabase project (the database)

1. Sign up at https://supabase.com (free tier is enough)
2. **New project** → pick a name → choose a strong DB password → region
   **Southeast Asia (Singapore)** for lowest latency from Vietnam → Create
3. Wait ~2 minutes for the project to provision
4. On the project's main dashboard page, click the **Connect** button at the
   top of the page. A modal opens with connection options.
5. Choose the **Transaction pooler** tab (NOT "Direct connection" — pooler
   works better for GitHub Actions and Streamlit Cloud, which spin up
   short-lived processes).
6. Copy the URI. It looks like:
   `postgresql://postgres.xxxxx:[YOUR-PASSWORD]@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres`
7. **Replace `[YOUR-PASSWORD]`** with the database password you set in step 2.
   If you forgot it, reset it on the same page.
8. **Save this string somewhere safe — you'll paste it into GitHub and Streamlit Cloud.**

> Can't see the Connect button? Alternate path: left sidebar → **⚙️ Project
> Settings → Database → Connection string**. Same info, just hidden in settings.

> ⚠️ The free tier pauses if the project sees zero activity for 7 days.
> Our daily GitHub Actions cron prevents that. If you ever stop the cron,
> the project will pause and the team will see errors until you un-pause it.

---

## Step 3 — Copy the existing data over (optional but recommended)

If you have local SQLite data you want to preserve:

```bash
export DATABASE_URL='postgresql://postgres.xxxxx:PASSWORD@host:6543/postgres'
pip install -r requirements.txt
python scripts/migrate_sqlite_to_postgres.py
```

You'll see something like:

```
✓ articles  : 1,234 new (skipped 0 dupes)
✓ usage_log : 87 inserted
Migration complete.
```

Safe to re-run — it skips anything already in Postgres.

If you'd rather start fresh, skip this step. The first GitHub Actions cron
run will populate the new database from scratch.

---

## Step 4 — Add secrets to GitHub Actions

This is what makes the daily scrape run automatically.

On your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

Add each of these:

| Secret name             | Value                                                       |
|-------------------------|-------------------------------------------------------------|
| `DATABASE_URL`          | The Supabase connection string from Step 2                  |
| `ANTHROPIC_API_KEY`     | Your Claude API key (`sk-ant-...`)                          |
| `FIRECRAWL_API_KEY`     | Your Firecrawl key (optional but recommended)               |
| `FACEBOOK_ACCESS_TOKEN` | Long-lived Page token (optional, only if doing FB scraping) |
| `FACEBOOK_APP_ID`       | Optional alternate to access token                          |
| `FACEBOOK_APP_SECRET`   | Optional alternate to access token                          |

Once added, go to the **Actions** tab → "Daily Scrape" workflow → click
**Run workflow** to test it manually. Should finish green in 2–5 minutes.

After that, it runs automatically every day at **07:00 GMT+7** (00:00 UTC).
To change the schedule, edit the `cron:` line in `.github/workflows/daily_scrape.yml`.

---

## Step 5 — Deploy the dashboard on Streamlit Cloud

1. Sign up at https://share.streamlit.io with your GitHub account
2. **New app** → select the repo → main file: `dashboard/app.py` → branch: `main`
3. Click **Advanced settings** → **Secrets** → paste this (with real values):

```toml
[env]
DATABASE_URL = "postgresql://postgres.xxxxx:PASSWORD@host:6543/postgres"
ANTHROPIC_API_KEY = "sk-ant-..."
FIRECRAWL_API_KEY = "fc-..."
FACEBOOK_ACCESS_TOKEN = ""
FACEBOOK_APP_ID = ""
FACEBOOK_APP_SECRET = ""
```

> Format mirrors `.streamlit/secrets.toml.example` in the repo — same keys,
> same values.

4. Click **Deploy**. First build takes ~3 minutes.
5. You'll get a public URL like `https://your-app-name.streamlit.app`
6. **Settings → Sharing → Viewer access**: set to "Only specific people"
   and add the team's email addresses, OR keep it public if there's nothing
   sensitive on the dashboard (everything is already public news).

The dashboard now reads from Supabase. Every time GitHub Actions runs the
daily scrape, fresh data lands in Supabase and the dashboard updates
(refresh the page or wait 60 seconds for the auto-refresh).

---

## What the team needs to know

Send them this note:

> **Home Loan Intel dashboard:** `https://your-app-name.streamlit.app`
>
> Updated every morning around 7 AM. Refresh the page to see the latest.
>
> If it shows an error or stops updating for more than 2 days, contact
> [your replacement or IT contact] — there's a deployment guide in the repo.

---

## Troubleshooting

**"DATABASE_URL must be set" when running locally**
You don't need it locally — without it, the code falls back to the SQLite
file at `data/social_listening.db`. Only set `DATABASE_URL` when you want
to talk to Supabase.

**Dashboard shows "No articles match" after deploy**
The Supabase tables exist but are empty — wait for the first GitHub Actions
run, or trigger one manually from the Actions tab.

**GitHub Action fails on `ModuleNotFoundError`**
Check `requirements.txt` is committed and the workflow's Python version
(currently 3.11) is compatible with all packages.

**Supabase project paused itself**
Visit your Supabase project dashboard → click "Restore" / "Unpause".
This shouldn't happen as long as the daily cron runs.

**Insight report (Tab 4) costs too much**
The "Generate Report" button calls Claude Opus, which is expensive
(~$0.05–0.20 per report). The Cost Tracker tab shows exactly what each
call cost. To restrict access, make the Streamlit Cloud app private
(Step 5 → Sharing).

---

## Local development (after deploy)

To keep developing locally without touching production data:

```bash
unset DATABASE_URL          # falls back to local SQLite
streamlit run dashboard/app.py
```

To test against production data:

```bash
export DATABASE_URL='postgresql://...'   # the Supabase URL
streamlit run dashboard/app.py
```

The dashboard and scrapers work identically against either backend.

---

## What you control (admin checklist)

Before handing off, make sure someone on the team has:

- [ ] Admin access to the GitHub repo
- [ ] Owner access to the Supabase project (Settings → Team)
- [ ] Owner access to the Streamlit Cloud app
- [ ] The Anthropic API key (or a separate company key on the same billing)
- [ ] The Firecrawl key (if used)
- [ ] Read access to the Facebook page tokens (if used)

If only one person has these and they leave, the whole thing dies.
Always grant access to at least two people.
