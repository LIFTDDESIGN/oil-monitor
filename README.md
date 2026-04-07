# Oil & Market Alert Monitor

Monitors Brent crude oil and the S&P 500 every 30 minutes using GitHub Actions.
Sends an email alert when any of the four threshold conditions from the Iran conflict
oil shock analysis are triggered.

## Alert thresholds

| Alert | Condition | Historical parallel |
|---|---|---|
| Oil peak signal | Oil drops >5% from its tracked high | Starting gun for 7–12 month crash countdown |
| Crash window open | S&P 500 below 5,900 (-15.5% from ATH) | 1990 Gulf War floor |
| Base case confirmed | S&P 500 below 5,200 (-25.5% from ATH) | 1973 OPEC embargo trajectory |
| Escalation | S&P 500 below 4,200 (-39.8% from ATH) | 2008 financial crisis territory |

---

## Setup — 5 steps

### Step 1 — Create a GitHub account (if you don't have one)
Go to https://github.com and sign up. It's free.

### Step 2 — Create a new repository
1. Click the **+** icon in the top right → **New repository**
2. Name it anything, e.g. `oil-monitor`
3. Set it to **Public** (keeps it within the free tier comfortably)
4. Click **Create repository**

### Step 3 — Upload these files
Upload all three files into your new repo, keeping the folder structure exactly as shown:

```
oil-monitor/
├── .github/
│   └── workflows/
│       └── market_alert.yml
├── monitor.py
├── state.json
└── README.md
```

The easiest way: on the repo page, click **uploading an existing file** and drag them in.
Make sure `.github/workflows/market_alert.yml` is in the correct folder path.

To create the folder structure on GitHub:
1. Click **Add file** → **Create new file**
2. In the filename box, type `.github/workflows/market_alert.yml`
   (GitHub automatically creates the folders when you use `/`)
3. Paste in the contents of `market_alert.yml`
4. Repeat for `monitor.py` and `state.json` (these go in the root, no subfolders)

### Step 4 — Set up Gmail for sending alerts

You need a Gmail app password (this is different from your regular Gmail password):

1. Go to your Google account: https://myaccount.google.com
2. Click **Security** in the left sidebar
3. Under "How you sign in to Google", make sure **2-Step Verification** is ON
   (If not, enable it first — required for app passwords)
4. Search for **App passwords** in the search bar at the top
5. Click **App passwords**
6. Under "Select app", choose **Mail**
7. Under "Select device", choose **Other** and type `Oil Monitor`
8. Click **Generate**
9. Copy the 16-character password shown (e.g. `abcd efgh ijkl mnop`)
   — you only see this once, save it

### Step 5 — Add secrets to GitHub

1. In your GitHub repo, click **Settings** (top menu)
2. In the left sidebar, click **Secrets and variables** → **Actions**
3. Click **New repository secret** and add each of these three secrets:

| Secret name | Value |
|---|---|
| `EMAIL_FROM` | Your Gmail address, e.g. `yourname@gmail.com` |
| `EMAIL_TO` | Where to send alerts (can be the same Gmail, or any email) |
| `EMAIL_PASSWORD` | The 16-character app password from Step 4 |

---

## Test it manually

Once the secrets are set up, go to your repo → **Actions** tab →
click **Oil & Market Alert Monitor** → click **Run workflow** → **Run workflow**.

Watch the run complete. Check your email. If something goes wrong, click the
failed run to see the error log.

---

## How it works

- GitHub runs `monitor.py` every 30 minutes on their servers (free)
- The script fetches Brent crude (ticker: `BZ=F`) and S&P 500 (`^GSPC`) from Yahoo Finance
- It compares prices against the four thresholds
- If a threshold is newly crossed, it sends you an HTML email with full context
- It saves `state.json` back to the repo so it remembers which alerts have already fired
  (you won't get spammed with the same alert repeatedly)
- Alerts auto-reset if the condition clears (e.g. oil recovers above the peak-drop threshold)

---

## Adjust the check frequency

In `market_alert.yml`, change the cron schedule:

| Schedule | Cron |
|---|---|
| Every 15 minutes | `*/15 * * * *` |
| Every 30 minutes | `*/30 * * * *` (default) |
| Every hour | `0 * * * *` |
| Market hours only (9am–5pm ET, Mon–Fri) | `*/30 13-21 * * 1-5` |

Note: GitHub's free tier gives 2,000 minutes/month for private repos.
At 30-minute intervals, each run takes ~30 seconds, so ~720 minutes/month — well within limits.
Public repos have unlimited free minutes.

---

## Files

- `monitor.py` — the monitoring script
- `.github/workflows/market_alert.yml` — the GitHub Actions schedule
- `state.json` — tracks oil high and which alerts have fired (auto-updated by the bot)
