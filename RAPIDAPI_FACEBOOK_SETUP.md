# Facebook scraping via RapidAPI — 5-minute setup

A bridge for collecting Facebook signal while waiting for Meta's Graph API
app review (which can take 1–2 weeks). Uses the **Facebook Scraper3** service
on the RapidAPI marketplace.

**Time required:** ~5 minutes
**Cost:** Free tier covers 30 calls/day (≈ 15 pages monitored daily).
Paid is $9.99/mo for 10k calls/day.

---

## What you get

- Public posts from any Facebook page (Vietcombank, Techcombank, VPBank,
  MBBank, and any other page name we add to `config/sources.yaml`)
- Same article fields as the official Graph API scraper — drops straight
  into the dashboard alongside news + forum data
- Auto-activates the moment the API key is in `.env`

## Steps

1. Open https://rapidapi.com and sign up (Google login is fine).
2. Search for **Facebook Scraper3** — the listing by *Glavier*.
3. Click **Subscribe to Test** and pick the **Basic (Free)** plan — 30
   calls per day, no credit card needed for the trial.
4. Once subscribed, click any endpoint in the left sidebar (e.g.
   `/search/pages`). The right panel shows **Code Snippets** with your
   personal **`x-rapidapi-key`** header. Copy that key.
5. Open the project's `.env` file and add a line:

   ```
   RAPIDAPI_KEY=your_key_here
   ```

That's it. Next time the daily scrape runs (or `python3 -m pipeline.collector`
is invoked manually), Facebook posts will start landing in the dashboard.

## Verifying it works

From the project root:

```bash
python3 -m scrapers.facebook_scraper3
```

You should see lines like:

```
INFO Facebook (RapidAPI): Vietcombank
  → 20 posts fetched
  → 3 relevant posts from Vietcombank
```

If you see `RAPIDAPI_KEY not set — skipping`, your `.env` change didn't load.
Try restarting the shell or running with `dotenv` explicitly.

## Adding more pages to monitor

Edit `config/sources.yaml`:

```yaml
facebook_pages:
  - name: Vietcombank
    page_id: "Vietcombank"
  - name: BIDV                    # add this
    page_id: "BIDVbank"           # the Facebook username (URL slug)
  - name: ACB
    page_id: "ACB.vn"
```

The `page_id` field here is the Facebook **username** (the slug from
`facebook.com/<slug>/`). The RapidAPI scraper turns that into the numeric
ID automatically via its `/search/pages` endpoint.

## Limits to know about

- **Free tier: 30 calls/day.** Each monitored page costs 2 calls
  (1 page-lookup + 1 posts-fetch). So free tier = up to 15 pages monitored
  daily. Past that, upgrade to Pro ($9.99/mo, 10k calls).
- **No groups, no keyword search on the free tier.** Those endpoints exist
  but cost more — we can add them later if the bank wants deeper coverage.
- **Reliability:** RapidAPI services scrape the public Facebook surface, so
  they break occasionally when Meta changes their UI. The maintainer usually
  patches within days. If you see "0 relevant posts" across all pages for a
  week, that's likely an API outage — not your data going dry.

## Switching to the official Graph API later

When the Meta App ID + Secret eventually arrive, just add them to `.env`:

```
FACEBOOK_APP_ID=...
FACEBOOK_APP_SECRET=...
```

The collector prefers the Meta scraper when both are set — RapidAPI quietly
sits in standby as a fallback. No code change needed.
