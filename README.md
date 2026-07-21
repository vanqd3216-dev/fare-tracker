# Bay Area Cloud Fare Tracker

Runs **hourly on GitHub's servers** — so it keeps tracking prices even when your
computer is off or the Claude app is closed. Every hour it checks each route in
`flight-watchlist.json` from all three Bay Area airports, keeps the cheapest,
appends the result to `fares_log.csv` (your permanent price history, committed
back into the repo), and **emails you** when a fare drops or hits a target.

**Data source:** real **Google Flights** fares via the free [`fast-flights`](https://pypi.org/project/fast-flights/)
library — no API key, no cost. It reads Google Flights' internal data feed
directly. Because that feed is unofficial, the library can occasionally break if
Google changes something (usually patched quickly) or rate-limit if queried too
aggressively; for a handful of routes a few times an hour it's reliable.

There is no server to run and no cost — GitHub Actions is free for this.

---

## One-time setup (~7 minutes)

No API key is needed — the fare data source is free.

### 1. Create the GitHub repo
1. Create a free account at <https://github.com> if you don't have one.
2. Click **New repository** → name it e.g. `fare-tracker` → set it **Private** → Create.
3. Upload the **contents of this `cloud-fare-tracker` folder** to the repo root
   (drag-and-drop `track.py`, `flight-watchlist.json`, `requirements.txt`,
   `README.md`, and the `.github` folder). The `.github` folder must sit at the
   top level of the repo.

### 2. (Optional) Add email-alert secrets
Only needed if you want email alerts on drops/targets. In the repo, go to
**Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret name  | Value                                                          |
|--------------|----------------------------------------------------------------|
| `EMAIL_USER` | a Gmail address to send alerts **from**                        |
| `EMAIL_PASS` | a Gmail **App Password** (see below) — not your login password |
| `EMAIL_TO`   | where to send alerts (defaults to `EMAIL_USER`)                |

**Gmail App Password:** enable 2-Step Verification on your Google account, then
go to <https://myaccount.google.com/apppasswords>, create an app password, and
paste that 16-character value as `EMAIL_PASS`. Skip this section entirely and the
tracker still logs prices to the CSV — it just won't email.

### 3. Turn it on
1. Open the **Actions** tab → if prompted, click **"I understand my workflows, enable them."**
2. Select **Fare tracker** → **Run workflow** to do a first run now.
3. After it finishes, check `fares_log.csv` in the repo — you should see rows.

That's it. From now on it runs every hour automatically.

---

## Changing what it tracks

Edit `flight-watchlist.json`:

- **Add/remove routes** — copy a line in `routes`, set `to` (destination IATA
  code) and a `label`.
- **Set a target price** — change `"target": null` to e.g. `"target": 220` to be
  emailed the moment that route is $220 or less.
- **Pin a departure date** — add `"date": "2026-09-10"` to a route, or change the
  top-level `departureDate`.
- **Alert sensitivity** — `alertOnDropPct` (default 10) is the % drop vs. the last
  check that triggers an email.

Commit the change and the next run uses it.

---

## Notes & limits

- **Data source:** live Google Flights fares via `fast-flights`. Always confirm
  the final price on the booking page before purchasing. If a run logs no data
  for a route, Google may have rate-limited that request — the next hourly run
  normally recovers.
- **Timing:** GitHub's scheduled runs are usually on time but can be delayed a few
  minutes during peak load; occasional hours may be skipped by GitHub. For
  near-exact hourly data this is more than good enough.
- **This is separate** from the in-app dashboard and its scheduled task. This
  cloud CSV is the always-on record; the dashboard chart reflects whenever you
  have it open.
