# Oil & Market Alert Monitor — v2

Monitors 6 indicators every 30 minutes via GitHub Actions (free, no server needed).
Sends instant email alerts when thresholds are crossed, plus a daily 08:00 UTC digest.

## Indicators

| Indicator | Source | What it signals |
|---|---|---|
| Brent crude price | Yahoo Finance `BZ=F` | Direct oil shock level |
| S&P 500 drawdown | Yahoo Finance `^GSPC` | Market damage |
| VIX fear index | Yahoo Finance `^VIX` | Panic / capitulation proximity |
| Credit stress (HYG) | Yahoo Finance `HYG` | Credit market cracking (leads equities) |
| Oil contango flip | Yahoo Finance `USO` vs `USL` | Market pricing oil shock as temporary |
| Confirmed oil peak | 3-check rolling buffer | Strong peak signal, not a blip |

## Alert thresholds

| Alert | Condition | Significance |
|---|---|---|
| Oil peak — early | Oil drops >5% from tracked high | Single-check warning |
| Oil peak — confirmed | 3 consecutive checks >5% below high | High-confidence peak signal |
| VIX spike | VIX > 30 | Fear elevated — bottom 3–6 weeks out |
| VIX capitulation | VIX > 40 | Extreme fear — likely near actual bottom |
| Credit stress | HYG down >8% from 3-month high | Credit cracking before equities |
| Oil contango | USO underperforming USL by >1% (5-day) | Market pricing in shock resolution |
| Crash window open | S&P < 5,900 (−15.5% from ATH) | Correction zone entered |
| Base case confirmed | S&P < 5,200 (−25.5% from ATH) | 1973-style trajectory |
| Escalation | S&P < 4,200 (−39.8% from ATH) | 2008-level crash |

## Composite score (0–10)

Every run computes a single signal score:

| Score | Label | Meaning |
|---|---|---|
| 0–3 | Low | No significant stress |
| 3–5 | Guarded | Early warning signs |
| 5–7 | Elevated | Multiple indicators active |
| 7–8.5 | High | Serious — review positions |
| 8.5–10 | Critical | All indicators firing |

## Emails you'll receive

1. **Instant alert** — when any threshold is newly crossed
2. **Daily digest** — every morning at 08:00 UTC with the full scorecard

## Setup

Same 5 steps as v1 — see the original README.
Replace your existing `monitor.py`, `state.json`, and `market_alert.yml` with these new versions.
No new secrets needed.

## Updating from v1

Just replace the three files in your repo:
- `monitor.py` → drag the new version in via **Add file → Upload files**
- `state.json` → replace with the new version (resets alert state)
- `.github/workflows/market_alert.yml` → edit in place (click the file → pencil icon → paste new content)
