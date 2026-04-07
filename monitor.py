import yfinance as yf
import json
import smtplib
import os
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone

# ── Thresholds (from historical oil shock analysis) ──────────────────────────
ATH_SPX        = 6978   # S&P 500 all-time high, Jan 27 2026
OIL_PEAK_DROP  = 5.0    # % drop from oil high → peak signal
SPX_WATCH      = 5900   # -15.5% from ATH → crash window opens
SPX_BASE       = 5200   # -25.5% from ATH → 1973-style base case
SPX_ESCALATION = 4200   # -39.8% from ATH → 2008-level escalation

STATE_FILE = "state.json"

# ── State ─────────────────────────────────────────────────────────────────────
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {
            "oil_high": 113.0,
            "alerts_fired": [],
            "last_oil": None,
            "last_spx": None,
            "last_check": None
        }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ── Price fetching ────────────────────────────────────────────────────────────
def fetch_prices():
    """Fetch Brent crude (BZ=F) and S&P 500 (^GSPC) from Yahoo Finance."""
    oil  = yf.Ticker("BZ=F")
    spx  = yf.Ticker("^GSPC")
    oil_hist = oil.history(period="1d", interval="5m")
    spx_hist = spx.history(period="1d", interval="5m")
    if oil_hist.empty or spx_hist.empty:
        raise ValueError("Empty data returned from Yahoo Finance.")
    oil_price = float(oil_hist["Close"].iloc[-1])
    spx_price = float(spx_hist["Close"].iloc[-1])
    return oil_price, spx_price

# ── Email ─────────────────────────────────────────────────────────────────────
def send_email(subject, html_body):
    sender   = os.environ["EMAIL_FROM"]
    receiver = os.environ["EMAIL_TO"]
    password = os.environ["EMAIL_PASSWORD"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = receiver
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as srv:
        srv.ehlo()
        srv.starttls()
        srv.login(sender, password)
        srv.sendmail(sender, receiver, msg.as_string())

def build_email_body(alert_name, alert_desc, alert_color, oil, spx, state):
    spx_drop        = ((ATH_SPX - spx) / ATH_SPX) * 100
    oil_drop        = ((state["oil_high"] - oil) / state["oil_high"]) * 100
    now_str         = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")

    scenario = "Watch mode"
    if spx < SPX_ESCALATION:
        scenario = "Escalation — 2008-level"
    elif spx < SPX_BASE:
        scenario = "Base case — 1973-level"
    elif spx < SPX_WATCH:
        scenario = "Crash window open"

    return f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f5f5f3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f3;padding:32px 16px;">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;border:1px solid #e5e5e0;overflow:hidden;">

      <tr><td style="background:{alert_color};padding:20px 28px;">
        <p style="margin:0;font-size:11px;color:rgba(255,255,255,0.75);letter-spacing:0.06em;text-transform:uppercase;">Iran oil conflict monitor</p>
        <h1 style="margin:6px 0 0;font-size:20px;font-weight:500;color:#ffffff;">{alert_name}</h1>
      </td></tr>

      <tr><td style="padding:24px 28px;">
        <p style="margin:0 0 20px;font-size:14px;color:#555;line-height:1.6;">{alert_desc}</p>

        <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e5e0;border-radius:8px;overflow:hidden;margin-bottom:20px;">
          <tr style="background:#f9f9f7;">
            <td style="padding:10px 16px;font-size:12px;color:#888;">Brent crude</td>
            <td style="padding:10px 16px;font-size:14px;font-weight:500;color:#111;text-align:right;">${oil:.2f} / bbl</td>
          </tr>
          <tr>
            <td style="padding:10px 16px;font-size:12px;color:#888;border-top:1px solid #e5e5e0;">Oil high (tracked)</td>
            <td style="padding:10px 16px;font-size:14px;color:#111;text-align:right;border-top:1px solid #e5e5e0;">${state['oil_high']:.2f} / bbl</td>
          </tr>
          <tr style="background:#f9f9f7;">
            <td style="padding:10px 16px;font-size:12px;color:#888;border-top:1px solid #e5e5e0;">Oil drop from high</td>
            <td style="padding:10px 16px;font-size:14px;font-weight:500;color:#E24B4A;text-align:right;border-top:1px solid #e5e5e0;">&#8209;{oil_drop:.1f}%</td>
          </tr>
          <tr>
            <td style="padding:10px 16px;font-size:12px;color:#888;border-top:1px solid #e5e5e0;">S&amp;P 500</td>
            <td style="padding:10px 16px;font-size:14px;font-weight:500;color:#111;text-align:right;border-top:1px solid #e5e5e0;">{spx:,.0f}</td>
          </tr>
          <tr style="background:#f9f9f7;">
            <td style="padding:10px 16px;font-size:12px;color:#888;border-top:1px solid #e5e5e0;">From ATH (6,978)</td>
            <td style="padding:10px 16px;font-size:14px;font-weight:500;color:#E24B4A;text-align:right;border-top:1px solid #e5e5e0;">&#8209;{spx_drop:.1f}%</td>
          </tr>
          <tr>
            <td style="padding:10px 16px;font-size:12px;color:#888;border-top:1px solid #e5e5e0;">Scenario reading</td>
            <td style="padding:10px 16px;font-size:14px;font-weight:500;color:{alert_color};text-align:right;border-top:1px solid #e5e5e0;">{scenario}</td>
          </tr>
        </table>

        <table width="100%" cellpadding="0" cellspacing="0" style="background:#fdf3f3;border:1px solid #f5c1c1;border-radius:8px;padding:14px 16px;margin-bottom:20px;">
          <tr>
            <td style="font-size:12px;color:#791F1F;line-height:1.6;">
              <strong>Historical context:</strong> Based on the 5 major oil shock episodes (1973, 1979, 1990, 2008, 2022),
              once oil peaks the market typically takes <strong>7–12 months</strong> to reach its final bottom.
              The base case puts the S&amp;P floor at <strong>3,900–4,200</strong>.
              The escalation scenario floor is <strong>2,800–3,200</strong>.
            </td>
          </tr>
        </table>

      </td></tr>

      <tr><td style="padding:16px 28px;border-top:1px solid #e5e5e0;background:#f9f9f7;">
        <p style="margin:0;font-size:11px;color:#aaa;line-height:1.6;">
          Checked at {now_str} · Iran conflict monitor · Not financial advice.
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>
"""

# ── Alert logic ───────────────────────────────────────────────────────────────
ALERT_DEFS = [
    {
        "key":   "oil_peak",
        "color": "#3B6D11",
        "name":  "Oil peak signal",
        "desc":  lambda oil, spx, state: (
            f"Brent crude has dropped {((state['oil_high']-oil)/state['oil_high']*100):.1f}% "
            f"from its recent high of ${state['oil_high']:.2f}. "
            "Based on the 5 historical oil shock episodes, this may signal that oil has peaked. "
            "The market crash countdown clock typically starts here — expect the S&P 500 bottom "
            "roughly 7–12 months from now."
        ),
        "condition": lambda oil, spx, state: (
            (state["oil_high"] - oil) / state["oil_high"] * 100 >= OIL_PEAK_DROP
        ),
    },
    {
        "key":   "crash_window",
        "color": "#BA7517",
        "name":  "Crash window open — S&P below 5,900",
        "desc":  lambda oil, spx, state: (
            f"The S&P 500 is at {spx:,.0f}, down "
            f"{((ATH_SPX-spx)/ATH_SPX*100):.1f}% from the January 2026 all-time high of 6,978. "
            "This is the correction threshold seen in all five historical oil shock episodes. "
            "Consistent with the quick-resolution (1990) scenario floor."
        ),
        "condition": lambda oil, spx, state: spx < SPX_WATCH,
    },
    {
        "key":   "base_case",
        "color": "#185FA5",
        "name":  "Base case confirmed — 1973-style crash",
        "desc":  lambda oil, spx, state: (
            f"The S&P 500 is at {spx:,.0f}, down "
            f"{((ATH_SPX-spx)/ATH_SPX*100):.1f}% from ATH. "
            "We are now in 1973 OPEC embargo territory. "
            "The historical base-case bottom is 3,900–4,200 on the S&P 500. "
            "Recession is likely being priced in."
        ),
        "condition": lambda oil, spx, state: spx < SPX_BASE,
    },
    {
        "key":   "escalation",
        "color": "#E24B4A",
        "name":  "ESCALATION — 2008-level crash confirmed",
        "desc":  lambda oil, spx, state: (
            f"The S&P 500 is at {spx:,.0f}, down "
            f"{((ATH_SPX-spx)/ATH_SPX*100):.1f}% from ATH. "
            "This is 2008 Global Financial Crisis territory. "
            "Historical pattern from the combined 1973+2008 scenario puts the floor at 2,800–3,200. "
            "Full global recession is the base expectation at this level."
        ),
        "condition": lambda oil, spx, state: spx < SPX_ESCALATION,
    },
]

def check_alerts(oil, spx, state):
    fired_set = set(state.get("alerts_fired", []))
    new_alerts = []

    # Track oil high
    if oil > state.get("oil_high", 0):
        state["oil_high"] = round(oil, 2)
        print(f"  New oil high tracked: ${state['oil_high']:.2f}")

    for defn in ALERT_DEFS:
        triggered = defn["condition"](oil, spx, state)
        key       = defn["key"]

        if triggered and key not in fired_set:
            new_alerts.append(defn)
            fired_set.add(key)
            print(f"  ALERT TRIGGERED: {defn['name']}")

        elif not triggered and key in fired_set:
            # Condition resolved — reset so it can fire again if re-crossed
            fired_set.discard(key)
            print(f"  Alert reset (condition cleared): {key}")

    state["alerts_fired"] = sorted(fired_set)
    return new_alerts, state

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n── Oil Monitor run: {now} ──")

    state = load_state()

    try:
        oil, spx = fetch_prices()
        print(f"  Brent crude : ${oil:.2f}/bbl")
        print(f"  S&P 500     : {spx:,.0f}")
    except Exception as exc:
        print(f"  ERROR fetching prices: {exc}")
        sys.exit(1)

    state["last_oil"]   = round(oil, 2)
    state["last_spx"]   = round(spx, 0)
    state["last_check"] = now

    new_alerts, state = check_alerts(oil, spx, state)

    if new_alerts:
        for defn in new_alerts:
            desc = defn["desc"](oil, spx, state)
            body = build_email_body(defn["name"], desc, defn["color"], oil, spx, state)
            try:
                send_email(f"[Oil Monitor] {defn['name']}", body)
                print(f"  Email sent: {defn['name']}")
            except Exception as exc:
                print(f"  Email error: {exc}")
    else:
        print("  No new thresholds crossed. All clear.")

    save_state(state)
    print("── Done ──\n")

if __name__ == "__main__":
    main()
