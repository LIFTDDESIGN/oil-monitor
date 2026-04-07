"""
Oil & Market Alert Monitor — v3
─────────────────────────────────────────────────────────────────────────────
Indicators tracked:
  1. Brent crude price          → 4 threshold levels
  2. S&P 500 drawdown           → 4 threshold levels
  3. VIX (fear index)           → spike alert at 30, capitulation at 40
  4. Credit stress (HYG ETF)    → drop >8% from 3-month high
  5. Oil contango flip          → USO vs USL momentum divergence
  6. Confirmed oil peak         → 3 consecutive checks >5% below oil high
  7. Composite signal score     → 0–10 combining all indicators

Delivery:
  - Email: instant alert + daily 08:00 UTC digest
  - SMS:   instant alert via email-to-SMS gateway (free, no extra accounts)

SMS setup — add these two secrets in GitHub → Settings → Secrets → Actions:
  SMS_TO      your 10-digit number, e.g. 2125551234
  SMS_CARRIER gateway address for your carrier (see CARRIERS dict below)
─────────────────────────────────────────────────────────────────────────────
"""

import yfinance as yf
import json, smtplib, os, sys
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# SMS via Twilio — add these three secrets in GitHub → Settings → Secrets → Actions:
#   TWILIO_SID    — Account SID from twilio.com/console
#   TWILIO_TOKEN  — Auth Token from twilio.com/console
#   TWILIO_FROM   — Your Twilio number, e.g. +14155551234
#   SMS_TO        — Your UK mobile, e.g. +447911123456

# ── Constants ─────────────────────────────────────────────────────────────────
ATH_SPX         = 6978    # S&P 500 all-time high, Jan 27 2026
OIL_PREWAR      = 72      # Brent crude pre-conflict baseline
OIL_PEAK_DROP   = 5.0     # % drop from tracked high to trigger peak signal
OIL_PEAK_CHECKS = 3       # Consecutive checks needed to confirm peak
SPX_WATCH       = 5900    # −15.5% from ATH
SPX_BASE        = 5200    # −25.5% from ATH (1973-style)
SPX_ESCALATION  = 4200    # −39.8% from ATH (2008-style)
VIX_SPIKE       = 30      # Fear spike threshold
VIX_CAPITULATE  = 40      # Capitulation / likely bottom zone
HYG_STRESS_PCT  = 8.0     # HYG drop from 3-month high → credit stress
CONTANGO_THRESH = -1.0    # USO 5-day momentum minus USL 5-day momentum (%)

STATE_FILE = "state.json"

# ── State ─────────────────────────────────────────────────────────────────────
def load_state():
    defaults = {
        "oil_high":         113.0,
        "hyg_3m_high":      None,
        "oil_peak_buffer":  [],     # Last N oil readings for confirmation
        "alerts_fired":     [],
        "last_oil":         None,
        "last_spx":         None,
        "last_vix":         None,
        "last_hyg":         None,
        "last_contango":    None,
        "last_score":       None,
        "last_check":       None,
    }
    try:
        with open(STATE_FILE) as f:
            saved = json.load(f)
            defaults.update(saved)
    except Exception:
        pass
    return defaults

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ── Price fetching ────────────────────────────────────────────────────────────
def fetch_series(ticker, period="3mo", interval="1d"):
    t = yf.Ticker(ticker)
    df = t.history(period=period, interval=interval)
    if df.empty:
        raise ValueError(f"No data for {ticker}")
    return df["Close"]

def fetch_all():
    """Returns dict of current prices and supporting data."""
    results = {}

    # Core: Brent crude, S&P 500, VIX
    for key, sym in [("oil", "BZ=F"), ("spx", "^GSPC"), ("vix", "^VIX")]:
        s = fetch_series(sym, period="5d", interval="5m")
        results[key] = float(s.iloc[-1])

    # Credit stress: HYG (iShares High Yield Bond ETF)
    hyg = fetch_series("HYG", period="3mo", interval="1d")
    results["hyg_now"]    = float(hyg.iloc[-1])
    results["hyg_3m_high"]= float(hyg.max())

    # Contango proxy: USO (1-month WTI) vs USL (12-month WTI)
    uso = fetch_series("USO", period="10d", interval="1d")
    usl = fetch_series("USL", period="10d", interval="1d")
    uso_ret = (uso.iloc[-1] - uso.iloc[0]) / uso.iloc[0] * 100
    usl_ret = (usl.iloc[-1] - usl.iloc[0]) / usl.iloc[0] * 100
    results["contango_spread"] = round(uso_ret - usl_ret, 2)  # negative = contango forming

    return results

# ── Composite score (0–10) ────────────────────────────────────────────────────
def compute_score(oil, spx, vix, hyg_drop_pct, contango_spread, oil_peak_confirmed):
    score = 0.0

    # Oil level (0–3 pts): $72 baseline → $168+ = max
    oil_pts = min(3.0, max(0.0, (oil - OIL_PREWAR) / (168 - OIL_PREWAR) * 3))
    score += oil_pts

    # S&P drawdown (0–3 pts): 0% → 60% drop = max
    spx_drop = (ATH_SPX - spx) / ATH_SPX * 100
    spx_pts  = min(3.0, max(0.0, spx_drop / 60 * 3))
    score += spx_pts

    # VIX (0–2 pts): 20 = 0pts, 50+ = 2pts
    vix_pts = min(2.0, max(0.0, (vix - 20) / 30 * 2))
    score += vix_pts

    # Credit stress (0–1 pt)
    score += 1.0 if hyg_drop_pct >= HYG_STRESS_PCT else 0.0

    # Contango confirmed (0–1 pt)
    score += 1.0 if contango_spread <= CONTANGO_THRESH else 0.0

    return round(min(10.0, score), 1)

def score_label(score):
    if score < 3:   return "Low",    "#3B6D11"
    if score < 5:   return "Guarded","#BA7517"
    if score < 7:   return "Elevated","#185FA5"
    if score < 8.5: return "High",   "#D85A30"
    return              "Critical",  "#E24B4A"

# ── Alert definitions ─────────────────────────────────────────────────────────
def build_alerts(data, state):
    oil             = data["oil"]
    spx             = data["spx"]
    vix             = data["vix"]
    hyg_now         = data["hyg_now"]
    hyg_3m_high     = data["hyg_3m_high"]
    contango        = data["contango_spread"]
    hyg_drop_pct    = (hyg_3m_high - hyg_now) / hyg_3m_high * 100 if hyg_3m_high else 0
    spx_drop        = (ATH_SPX - spx) / ATH_SPX * 100
    oil_drop        = (state["oil_high"] - oil) / state["oil_high"] * 100 if state["oil_high"] else 0

    # Update oil peak buffer
    buf = list(state.get("oil_peak_buffer", []))
    buf.append(round(oil, 2))
    if len(buf) > OIL_PEAK_CHECKS:
        buf = buf[-OIL_PEAK_CHECKS:]
    state["oil_peak_buffer"] = buf
    peak_confirmed = (
        len(buf) >= OIL_PEAK_CHECKS and
        all((state["oil_high"] - p) / state["oil_high"] * 100 >= OIL_PEAK_DROP for p in buf)
    )

    defs = [
        {
            "key":   "oil_peak_early",
            "color": "#3B6D11",
            "name":  "Oil peak signal (early)",
            "desc":  (f"Brent crude has dropped {oil_drop:.1f}% from its tracked high of "
                      f"${state['oil_high']:.2f}. Single reading — awaiting confirmation across "
                      f"3 consecutive checks before upgrading to confirmed peak."),
            "on":    oil_drop >= OIL_PEAK_DROP and not peak_confirmed,
        },
        {
            "key":   "oil_peak_confirmed",
            "color": "#1D9E75",
            "name":  "Oil peak CONFIRMED",
            "desc":  (f"Brent crude has held more than {OIL_PEAK_DROP}% below its tracked high of "
                      f"${state['oil_high']:.2f} for {OIL_PEAK_CHECKS} consecutive checks. "
                      "This is the strongest oil peak signal — historically marks the start of the "
                      "7–12 month window to market bottom. High confidence trigger."),
            "on":    peak_confirmed,
        },
        {
            "key":   "vix_spike",
            "color": "#BA7517",
            "name":  "VIX fear spike — above 30",
            "desc":  (f"VIX is at {vix:.1f}. In all five historical oil shock episodes, VIX crossing "
                      "30 preceded the final market bottom by 3–6 weeks. This is a leading indicator "
                      "— the real capitulation may still be ahead."),
            "on":    vix >= VIX_SPIKE and vix < VIX_CAPITULATE,
        },
        {
            "key":   "vix_capitulation",
            "color": "#D85A30",
            "name":  "VIX capitulation zone — above 40",
            "desc":  (f"VIX is at {vix:.1f}. Above 40 has historically marked the final capitulation "
                      "zone — extreme fear that typically signals the market is near its bottom, "
                      "not far from it. This is where the 2008 and 1973 crashes found their floor."),
            "on":    vix >= VIX_CAPITULATE,
        },
        {
            "key":   "credit_stress",
            "color": "#D85A30",
            "name":  "Credit stress — HYG bond ETF under pressure",
            "desc":  (f"HYG (high-yield bond ETF) is down {hyg_drop_pct:.1f}% from its 3-month high "
                      f"(now ${hyg_now:.2f}, high was ${hyg_3m_high:.2f}). "
                      "Credit markets historically crack before equities fully sell off. "
                      "This is the signal the 2008 crash gave earliest — 6–8 weeks ahead of the S&P bottom."),
            "on":    hyg_drop_pct >= HYG_STRESS_PCT,
        },
        {
            "key":   "contango",
            "color": "#534AB7",
            "name":  "Oil contango forming — futures curve shift",
            "desc":  (f"Near-term oil futures (USO) are underperforming longer-dated futures (USL) "
                      f"by {abs(contango):.1f}% over 5 days (spread: {contango:.1f}%). "
                      "This means traders are pricing current supply disruption as temporary. "
                      "Contango historically appears at or just after the oil price peak — "
                      "a potential sign the oil shock is peaking."),
            "on":    contango <= CONTANGO_THRESH,
        },
        {
            "key":   "crash_window",
            "color": "#BA7517",
            "name":  "Crash window open — S&P below 5,900",
            "desc":  (f"S&P 500 at {spx:,.0f} (−{spx_drop:.1f}% from ATH). "
                      "Crossed the correction threshold seen in all five historical oil shock episodes. "
                      "Consistent with the 1990 Gulf War scenario minimum drawdown."),
            "on":    spx < SPX_WATCH,
        },
        {
            "key":   "base_case",
            "color": "#185FA5",
            "name":  "Base case confirmed — 1973-style",
            "desc":  (f"S&P 500 at {spx:,.0f} (−{spx_drop:.1f}% from ATH). "
                      "1973 OPEC embargo territory. Historical base-case bottom: 3,900–4,200."),
            "on":    spx < SPX_BASE,
        },
        {
            "key":   "escalation",
            "color": "#E24B4A",
            "name":  "ESCALATION — 2008-level crash",
            "desc":  (f"S&P 500 at {spx:,.0f} (−{spx_drop:.1f}% from ATH). "
                      "2008 Global Financial Crisis territory. "
                      "Historical floor at this scenario: 2,800–3,200."),
            "on":    spx < SPX_ESCALATION,
        },
    ]
    return defs, {
        "hyg_drop_pct": hyg_drop_pct,
        "spx_drop": spx_drop,
        "oil_drop": oil_drop,
        "peak_confirmed": peak_confirmed,
    }

# ── Email builder ─────────────────────────────────────────────────────────────
def status_badge(condition, yes_label, no_label, yes_color, no_color="#888"):
    color = yes_color if condition else no_color
    label = yes_label if condition else no_label
    return (f'<span style="display:inline-block;padding:3px 10px;border-radius:20px;'
            f'background:{color}22;color:{color};font-size:11px;font-weight:500;">{label}</span>')

def build_alert_email(alert_def, data, state, computed, score):
    oil, spx, vix = data["oil"], data["spx"], data["vix"]
    hyg_now, contango = data["hyg_now"], data["contango_spread"]
    sl, sc = score_label(score)
    now_str = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    color = alert_def["color"]

    return _email_shell(
        header_color=color,
        header_tag="Alert",
        header_title=alert_def["name"],
        body_html=f"""
        <p style="font-size:14px;color:#444;line-height:1.7;margin:0 0 20px;">{alert_def['desc']}</p>
        {_scorecard(oil, spx, vix, hyg_now, contango, state, computed, score, sl, sc)}
        {_context_box()}
        """,
        footer=now_str
    )

def build_digest_email(data, state, computed, score, alert_defs):
    oil, spx, vix = data["oil"], data["spx"], data["vix"]
    hyg_now, contango = data["hyg_now"], data["contango_spread"]
    sl, sc = score_label(score)
    now_str = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")

    active = [d for d in alert_defs if d["on"]]
    active_html = ""
    if active:
        rows = "".join(
            f'<tr><td style="padding:8px 0;border-top:1px solid #eee;font-size:13px;color:{d["color"]};font-weight:500;">'
            f'{d["name"]}</td></tr>' for d in active
        )
        active_html = f"""
        <table width="100%" style="margin-bottom:20px;border-collapse:collapse;">
          <tr><td style="font-size:11px;color:#888;padding-bottom:6px;letter-spacing:.05em;text-transform:uppercase;">Active alerts</td></tr>
          {rows}
        </table>"""
    else:
        active_html = '<p style="color:#3B6D11;font-size:13px;margin-bottom:20px;">No thresholds currently breached — all clear.</p>'

    return _email_shell(
        header_color="#378ADD",
        header_tag="Daily digest — 08:00 UTC",
        header_title="Iran oil conflict — morning briefing",
        body_html=f"""
        {active_html}
        {_scorecard(oil, spx, vix, hyg_now, contango, state, computed, score, sl, sc)}
        {_context_box()}
        """,
        footer=now_str
    )

def _scorecard(oil, spx, vix, hyg_now, contango, state, computed, score, sl, sc):
    spx_drop      = computed["spx_drop"]
    oil_drop      = computed["oil_drop"]
    hyg_drop      = computed["hyg_drop_pct"]
    peak_conf     = computed["peak_confirmed"]
    contango_on   = contango <= CONTANGO_THRESH

    def row(label, value, badge_html, alt_bg=False):
        bg = ' style="background:#f9f9f7;"' if alt_bg else ''
        return (f'<tr{bg}>'
                f'<td style="padding:10px 14px;font-size:12px;color:#888;">{label}</td>'
                f'<td style="padding:10px 14px;font-size:13px;font-weight:500;color:#111;">{value}</td>'
                f'<td style="padding:10px 14px;text-align:right;">{badge_html}</td>'
                f'</tr>')

    score_color = sc
    return f"""
    <div style="margin-bottom:20px;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
        <span style="font-size:11px;color:#888;letter-spacing:.05em;text-transform:uppercase;">Signal scorecard</span>
        <span style="font-size:22px;font-weight:500;color:{score_color};">{score}/10
          <span style="font-size:13px;font-weight:400;"> — {sl}</span></span>
      </div>
      <table width="100%" style="border-collapse:collapse;border:1px solid #e5e5e0;border-radius:8px;overflow:hidden;">
        {row("Brent crude", f"${oil:.2f}/bbl",
             status_badge(oil > 120, f"+{((oil-OIL_PREWAR)/OIL_PREWAR*100):.0f}% from pre-war",
                          f"+{((oil-OIL_PREWAR)/OIL_PREWAR*100):.0f}% from pre-war", "#D85A30", "#3B6D11"))}
        {row("Oil peak signal", f"${state['oil_high']:.2f} high / −{oil_drop:.1f}% now",
             status_badge(peak_conf, "Confirmed", "Watching", "#1D9E75"), True)}
        {row("S&P 500", f"{spx:,.0f}  (−{spx_drop:.1f}% from ATH)",
             status_badge(spx < SPX_BASE, "Base case", "Watch" if spx < SPX_WATCH else "OK",
                          "#E24B4A" if spx < SPX_BASE else "#BA7517", "#3B6D11"))}
        {row("VIX (fear index)", f"{vix:.1f}",
             status_badge(vix >= VIX_SPIKE, "Spike" if vix < VIX_CAPITULATE else "Capitulation",
                          "Normal", "#D85A30" if vix < VIX_CAPITULATE else "#E24B4A"), True)}
        {row("Credit stress (HYG)", f"${hyg_now:.2f}  (−{hyg_drop:.1f}% from 3m high)",
             status_badge(hyg_drop >= HYG_STRESS_PCT, "Stressed", "Normal", "#D85A30"))}
        {row("Oil contango", f"USO vs USL: {contango:+.1f}%",
             status_badge(contango_on, "Forming", "Backwardation", "#534AB7"), True)}
      </table>
    </div>"""

def _context_box():
    return """
    <table width="100%" style="background:#fdf3f3;border:1px solid #f5c1c1;border-radius:8px;margin-bottom:20px;">
      <tr><td style="padding:14px 16px;font-size:12px;color:#791F1F;line-height:1.7;">
        <strong>Historical context:</strong> Based on 5 major oil shock episodes (1973, 1979, 1990, 2008, 2022).
        Once oil peaks, the S&P 500 typically bottoms <strong>7–12 months later</strong>.
        Base-case floor: <strong>3,900–4,200</strong>. Escalation floor: <strong>2,800–3,200</strong>.
        Strongest combined signal: oil peak confirmed + VIX &gt;30 + HYG stressed.
      </td></tr>
    </table>"""

def _email_shell(header_color, header_tag, header_title, body_html, footer):
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f5f5f3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
  <tr><td align="center">
    <table width="580" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;border:1px solid #e5e5e0;overflow:hidden;">
      <tr><td style="background:{header_color};padding:20px 28px;">
        <p style="margin:0 0 4px;font-size:11px;color:rgba(255,255,255,.7);letter-spacing:.06em;text-transform:uppercase;">{header_tag}</p>
        <h1 style="margin:0;font-size:19px;font-weight:500;color:#fff;">{header_title}</h1>
      </td></tr>
      <tr><td style="padding:24px 28px;">{body_html}</td></tr>
      <tr><td style="padding:14px 28px;border-top:1px solid #eee;background:#f9f9f7;">
        <p style="margin:0;font-size:11px;color:#bbb;">Iran conflict monitor · {footer} · Not financial advice.</p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""

# ── SMS via Twilio ────────────────────────────────────────────────────────────
def send_sms(message):
    """
    Sends an SMS via Twilio. Works with UK numbers.
    Requires four GitHub secrets:
      TWILIO_SID    — Account SID (from twilio.com/console)
      TWILIO_TOKEN  — Auth Token (from twilio.com/console)
      TWILIO_FROM   — Your Twilio number e.g. +14155551234
      SMS_TO        — Your UK mobile e.g. +447911123456
    If any secret is missing, SMS is skipped with a log message.
    """
    sid   = os.environ.get("TWILIO_SID",   "").strip()
    token = os.environ.get("TWILIO_TOKEN", "").strip()
    from_ = os.environ.get("TWILIO_FROM",  "").strip()
    to    = os.environ.get("SMS_TO",       "").strip()

    if not all([sid, token, from_, to]):
        missing = [k for k, v in {"TWILIO_SID": sid, "TWILIO_TOKEN": token,
                                   "TWILIO_FROM": from_, "SMS_TO": to}.items() if not v]
        print(f"  SMS skipped — missing secrets: {', '.join(missing)}")
        return

    import urllib.request, urllib.parse, base64, urllib.error

    url  = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    data = urllib.parse.urlencode({"From": from_, "To": to, "Body": message[:1600]}).encode()
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()

    req  = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            print(f"  SMS sent to {to} — SID: {result.get('sid', '?')}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  SMS error {e.code}: {body}")
    except Exception as e:
        print(f"  SMS error: {e}")

def build_sms(alert_name, oil, spx, vix, score):
    """Builds a short SMS under 160 chars."""
    sl, _ = score_label(score)
    return (
        f"OIL ALERT: {alert_name}\n"
        f"Oil ${oil:.0f} | S&P {spx:,.0f} | VIX {vix:.0f}\n"
        f"Score {score}/10 ({sl})"
    )

def build_digest_sms(oil, spx, vix, score, any_alerts):
    sl, _ = score_label(score)
    status = "Alerts active" if any_alerts else "All clear"
    return (
        f"Morning briefing\n"
        f"Oil ${oil:.0f} | S&P {spx:,.0f} | VIX {vix:.0f}\n"
        f"Score {score}/10 ({sl}) — {status}"
    )


def send_email(subject, html):
    sender   = os.environ["EMAIL_FROM"]
    receiver = os.environ["EMAIL_TO"]
    password = os.environ["EMAIL_PASSWORD"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = receiver
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.ehlo(); s.starttls(); s.login(sender, password)
        s.sendmail(sender, receiver, msg.as_string())

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now_utc = datetime.now(timezone.utc)
    print(f"\n── Oil Monitor v2 · {now_utc.strftime('%Y-%m-%d %H:%M UTC')} ──")

    state = load_state()

    try:
        data = fetch_all()
        print(f"  Brent    : ${data['oil']:.2f}")
        print(f"  S&P 500  : {data['spx']:,.0f}")
        print(f"  VIX      : {data['vix']:.1f}")
        print(f"  HYG      : ${data['hyg_now']:.2f}  (3m high ${data['hyg_3m_high']:.2f})")
        print(f"  Contango : {data['contango_spread']:+.2f}%  (USO−USL 5d momentum)")
    except Exception as e:
        print(f"  ERROR fetching data: {e}")
        sys.exit(1)

    # Update oil high
    if data["oil"] > state.get("oil_high", 0):
        state["oil_high"] = round(data["oil"], 2)
    if data["hyg_3m_high"] and (not state.get("hyg_3m_high") or data["hyg_3m_high"] > state["hyg_3m_high"]):
        state["hyg_3m_high"] = round(data["hyg_3m_high"], 2)

    alert_defs, computed = build_alerts(data, state)

    score = compute_score(
        data["oil"], data["spx"], data["vix"],
        computed["hyg_drop_pct"], data["contango_spread"],
        computed["peak_confirmed"]
    )
    sl, sc = score_label(score)
    print(f"  Score    : {score}/10 — {sl}")

    # ── Threshold alerts ──────────────────────────────────────────────────────
    fired_set = set(state.get("alerts_fired", []))
    for defn in alert_defs:
        key = defn["key"]
        if defn["on"] and key not in fired_set:
            print(f"  ALERT: {defn['name']}")
            # Email
            html = build_alert_email(defn, data, state, computed, score)
            try:
                send_email(f"[Oil Monitor] {defn['name']}", html)
                print(f"  Email sent.")
            except Exception as e:
                print(f"  Email error: {e}")
            # SMS
            sms = build_sms(defn["name"], data["oil"], data["spx"], data["vix"], score)
            send_sms(sms)
            fired_set.add(key)
        elif not defn["on"] and key in fired_set:
            fired_set.discard(key)
            print(f"  Reset: {key}")

    if not any(d["on"] for d in alert_defs):
        print("  No thresholds crossed.")

    # ── Daily digest at 08:00 UTC ─────────────────────────────────────────────
    if now_utc.hour == 8 and now_utc.minute < 30:
        print("  Sending daily digest...")
        any_alerts = any(d["on"] for d in alert_defs)
        # Email digest
        html = build_digest_email(data, state, computed, score, alert_defs)
        try:
            send_email(f"[Oil Monitor] Morning briefing — score {score}/10 ({sl})", html)
            print("  Digest email sent.")
        except Exception as e:
            print(f"  Digest email error: {e}")
        # SMS digest
        sms = build_digest_sms(data["oil"], data["spx"], data["vix"], score, any_alerts)
        send_sms(sms)

    # ── Save state ────────────────────────────────────────────────────────────
    state["alerts_fired"] = sorted(fired_set)
    state["last_oil"]     = round(data["oil"], 2)
    state["last_spx"]     = round(data["spx"], 0)
    state["last_vix"]     = round(data["vix"], 1)
    state["last_hyg"]     = round(data["hyg_now"], 2)
    state["last_contango"]= round(data["contango_spread"], 2)
    state["last_score"]   = score
    state["last_check"]   = now_utc.isoformat()
    save_state(state)
    print("── Done ──\n")

if __name__ == "__main__":
    main()
