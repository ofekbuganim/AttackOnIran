import os, json, requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

EVENT_SLUG = "us-strikes-iran-by"
GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
DATA_TRADES = "https://data-api.polymarket.com/trades"
STATE_FILE = "state.json"

GRACE_HOURS = 2
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

def tg_send(text: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    chat_id = os.environ["TELEGRAM_CHAT_ID"].strip()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=20)
    r.raise_for_status()

def parse_iso_z(s: str):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

def now_israel_date_str() -> str:
    return datetime.now(timezone.utc).astimezone(ISRAEL_TZ).strftime("%Y-%m-%d")

def format_israel_time(ts: int) -> str:
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(ISRAEL_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S Israel")

def should_send_daily(state: dict, key: str) -> bool:
    today = now_israel_date_str()
    return (state.get(key) or "") != today

def mark_daily(state: dict, key: str):
    state[key] = now_israel_date_str()

def fetch_active_markets():
    r = requests.get(GAMMA_EVENTS, params={"slug": [EVENT_SLUG], "limit": 10}, timeout=20)
    r.raise_for_status()
    events = r.json()
    ev = events[0]
    title = ev.get("title") or EVENT_SLUG

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=GRACE_HOURS)

    markets = {}
    for m in (ev.get("markets") or []):
        cid = m.get("conditionId")
        end_s = m.get("endDate")
        if not (cid and end_s):
            continue
        try:
            end_dt = parse_iso_z(end_s)
        except Exception:
            continue
        if end_dt >= cutoff:
            markets[cid] = {
                "slug": m.get("slug"),
                "question": m.get("question"),
                "endDate": end_s,
            }
    return title, markets

def increases_yes_exposure(trade: dict) -> bool:
    outcome = (trade.get("outcome") or "").strip().lower()
    side = (trade.get("side") or "").strip().upper()
    return (outcome == "yes" and side == "BUY") or (outcome == "no" and side == "SELL")

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            s = json.load(f)
            if not isinstance(s, dict):
                return {"last_ts": 0, "last_alive_date": "", "last_summary_date": ""}
            s.setdefault("last_ts", 0)
            s.setdefault("last_alive_date", "")
            s.setdefault("last_summary_date", "")
            return s
    except Exception:
        return {"last_ts": 0, "last_alive_date": "", "last_summary_date": ""}

def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)

def fetch_big_trades(condition_ids, threshold, limit=300):
    params = {
        "limit": limit,
        "market": ",".join(condition_ids),
        "filterType": "CASH",
        "filterAmount": threshold,
    }
    return requests.get(DATA_TRADES, params=params, timeout=20).json()

def send_daily_summary(markets: dict, threshold: float):
    """
    Sends TOP 10 biggest YES-side trades in the last 24 hours (Israel time shown).
    Uses the SAME threshold as alerts (you can change that if you want).
    """
    now_ts = int(datetime.now(timezone.utc).timestamp())
    since_ts = now_ts - 24 * 3600

    condition_ids = list(markets.keys())
    if not condition_ids:
        return

    trades = fetch_big_trades(condition_ids, threshold, limit=500)

    rows = []
    for t in trades:
        if (t.get("eventSlug") or "") != EVENT_SLUG:
            continue
        cid = t.get("conditionId")
        if cid not in markets:
            continue

        ts = int(t.get("timestamp") or 0)
        if ts < since_ts:
            continue

        if not increases_yes_exposure(t):
            continue

        cash = float(t.get("price", 0) or 0) * float(t.get("size", 0) or 0)
        rows.append((cash, ts, cid, t))

    rows.sort(key=lambda x: x[0], reverse=True)
    top = rows[:10]

    if not top:
        tg_send(f"📊 Daily summary (last 24h): No YES-side trades ≥ ${threshold:,.0f}.")
        return

    lines = [f"📊 Daily summary (top {len(top)} YES-side trades last 24h, ≥ ${threshold:,.0f})"]
    for cash, ts, cid, t in top:
        q = markets[cid].get("question") or markets[cid].get("slug") or "(unknown market)"
        lines.append(
            f"- ${cash:,.0f} | {format_israel_time(ts)}\n"
            f"  {q}\n"
            f"  {t.get('outcome')} {t.get('side')} | Tx {t.get('transactionHash')}"
        )

    tg_send("\n".join(lines))

def main():
    # Safer parsing: if secret is blank -> default 500000
    raw = (os.environ.get("THRESHOLD_USD") or "").strip()
    threshold = float(raw) if raw else 500000.0

    state = load_state()

    # Fetch markets once per run
    title, markets = fetch_active_markets()
    condition_ids = list(markets.keys())
    if not condition_ids:
        print("No active markets found.")
        return

    # A) Daily "still alive" (once per Israel day)
    if should_send_daily(state, "last_alive_date"):
        tg_send(f"✅ Polymarket watcher is alive (daily ping). Event: {title}")
        mark_daily(state, "last_alive_date")

    # B) Daily summary (once per Israel day)
    if should_send_daily(state, "last_summary_date"):
        try:
            send_daily_summary(markets, threshold)
        except Exception as e:
            tg_send(f"⚠️ Daily summary failed: {e}")
        mark_daily(state, "last_summary_date")

    last_ts = int(state.get("last_ts", 0))

    # Live alerts (new trades since last_ts)
    trades = fetch_big_trades(condition_ids, threshold, limit=300)

    hits = []
    newest_ts = last_ts

    for t in trades:
        if (t.get("eventSlug") or "") != EVENT_SLUG:
            continue
        cid = t.get("conditionId")
        if cid not in markets:
            continue

        t_ts = int(t.get("timestamp") or 0)
        if t_ts <= last_ts:
            continue

        if not increases_yes_exposure(t):
            continue

        cash = float(t.get("price", 0) or 0) * float(t.get("size", 0) or 0)
        meta = markets[cid]
        hits.append((t_ts, cash, meta, t))

        if t_ts > newest_ts:
            newest_ts = t_ts

    hits.sort(key=lambda x: x[0])  # old -> new

    for t_ts, cash, meta, t in hits:
        tg_send(
            "🚨 BIG YES-SIDE TRADE\n"
            f"{meta.get('question')}\n"
            f"EndDate: {meta.get('endDate')}\n"
            f"Trade time: {format_israel_time(t_ts)}\n"
            f"CASH ≈ ${cash:,.0f}\n"
            f"Outcome: {t.get('outcome')} | Side: {t.get('side')}\n"
            f"Tx: {t.get('transactionHash')}"
        )

    # Save state (IMPORTANT: keep daily keys too)
    state["last_ts"] = newest_ts
    save_state(state)

    print(f"Done. last_ts was {last_ts}, now {newest_ts}. Sent {len(hits)} alerts.")

if __name__ == "__main__":
    main()
