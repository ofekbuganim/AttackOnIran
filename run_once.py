import os, json, requests
from zoneinfo import ZoneInfo
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

EVENT_SLUG = "us-strikes-iran-by"
GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
DATA_TRADES = "https://data-api.polymarket.com/trades"
STATE_FILE = "state.json"

GRACE_HOURS = 2

def tg_send(text: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    chat_id = os.environ["TELEGRAM_CHAT_ID"].strip()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=20)
    r.raise_for_status()

def parse_iso_z(s: str):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

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

def trade_uid(t: dict) -> str:
    return str(t.get("transactionHash") or t.get("id") or f"{t.get('timestamp')}-{t.get('asset')}")

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_ts": 0}

def save_state(last_ts: int):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_ts": last_ts}, f)

def main():
    threshold = float(os.environ.get("THRESHOLD_USD", "500000"))
    state = load_state()
    last_ts = int(state.get("last_ts", 0))

    title, markets = fetch_active_markets()
    condition_ids = list(markets.keys())
    if not condition_ids:
        print("No active markets found.")
        return

    params = {
        "limit": 300,
        "market": ",".join(condition_ids),
        "filterType": "CASH",
        "filterAmount": threshold,
    }
    trades = requests.get(DATA_TRADES, params=params, timeout=20).json()

    # Filter to: our event + our markets + YES-direction + newer than last_ts
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

    # Sort old->new so notifications come in order
    hits.sort(key=lambda x: x[0])
    
    for t_ts, cash, meta, t in hits:
        israel = ZoneInfo("Asia/Jerusalem")
        dt = datetime.fromtimestamp(t_ts, tz=timezone.utc).astimezone(israel)
        dt_str = dt.strftime("%Y-%m-%d %H:%M:%S Israel")
        tg_send(
        "🚨 BIG YES-SIDE TRADE\n"
        f"{meta.get('question')}\n"
        f"EndDate: {meta.get('endDate')}\n"
        f"Trade time: {dt_str}\n"
        f"CASH ≈ ${cash:,.0f}\n"
        f"Outcome: {t.get('outcome')} | Side: {t.get('side')}\n"
        f"Tx: {t.get('transactionHash')}"
        )

    # Update state even if no hits (so we don't spam old trades if API ordering changes)
    save_state(newest_ts)
    print(f"Done. last_ts was {last_ts}, now {newest_ts}. Sent {len(hits)} alerts.")

if __name__ == "__main__":
    main()
