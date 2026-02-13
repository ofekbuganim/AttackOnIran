import os
import time
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

EVENT_SLUG = "us-strikes-iran-by"

GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
DATA_TRADES = "https://data-api.polymarket.com/trades"

GRACE_HOURS = 2
REFRESH_MARKETS_EVERY_SEC = 300

def tg_send(text: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    chat_id = os.environ["TELEGRAM_CHAT_ID"].strip()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=20)
    r.raise_for_status()

def parse_iso_z(s: str):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

def unix_now() -> int:
    return int(datetime.now(timezone.utc).timestamp())

def fetch_active_markets():
    r = requests.get(GAMMA_EVENTS, params={"slug": [EVENT_SLUG], "limit": 10}, timeout=20)
    r.raise_for_status()
    events = r.json()
    if not events:
        raise RuntimeError(f"No event found for slug={EVENT_SLUG}")
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
                "end_dt": end_dt,
            }

    return title, markets

def increases_yes_exposure(trade: dict) -> bool:
    outcome = (trade.get("outcome") or "").strip().lower()
    side = (trade.get("side") or "").strip().upper()
    return (outcome == "yes" and side == "BUY") or (outcome == "no" and side == "SELL")

def trade_uid(t: dict) -> str:
    return str(
        t.get("transactionHash")
        or t.get("id")
        or f"{t.get('timestamp')}-{t.get('asset')}-{t.get('size')}-{t.get('price')}"
    )

def ts_to_str(ts: int) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(ts)

def fetch_big_trades(condition_ids, threshold, limit=200):
    # Data API supports market list + CASH filter (>= threshold)
    params = {
        "limit": limit,
        "market": ",".join(condition_ids),
        "filterType": "CASH",
        "filterAmount": threshold,
    }
    return requests.get(DATA_TRADES, params=params, timeout=20).json()

def send_24h_recap(markets, condition_ids, threshold):
    now_ts = unix_now()
    since_ts = now_ts - 24 * 3600

    trades = fetch_big_trades(condition_ids, threshold, limit=500)

    # Filter to our event + YES direction + last 24h
    hits = []
    for t in trades:
        if (t.get("eventSlug") or "") != EVENT_SLUG:
            continue
        cid = t.get("conditionId")
        if cid not in markets:
            continue
        t_ts = int(t.get("timestamp") or 0)
        if t_ts < since_ts:
            continue
        if not increases_yes_exposure(t):
            continue

        cash = float(t.get("price", 0) or 0) * float(t.get("size", 0) or 0)
        meta = markets[cid]
        hits.append((t_ts, cash, meta.get("question"), meta.get("endDate"), t.get("side"), t.get("outcome"), t.get("transactionHash")))

    hits.sort(reverse=True, key=lambda x: x[0])  # newest first

    if not hits:
        tg_send(f"🕒 24h recap: no YES-side trades ≥ ${threshold:,.0f} in the last 24h.")
        return

    # Send a compact summary (top 10) to avoid spam
    top = hits[:10]
    lines = [f"🕒 24h recap (top {len(top)}): YES-side trades ≥ ${threshold:,.0f}"]
    for t_ts, cash, q, endd, side, outcome, tx in top:
        lines.append(f"- ${cash:,.0f} | {outcome}/{side} | {q} | {ts_to_str(t_ts)}")

    if len(hits) > 10:
        lines.append(f"(+{len(hits)-10} more)")

    tg_send("\n".join(lines))

def main():
    threshold = float(os.getenv("THRESHOLD_USD", "500000"))
    poll_seconds = float(os.getenv("POLL_SECONDS", "3"))
    send_recap = os.getenv("SEND_24H_RECAP", "1").strip() == "1"

    title, markets = fetch_active_markets()
    condition_ids = list(markets.keys())

    tg_send(
        f"✅ Watcher started\n"
        f"Event: {title}\n"
        f"Active markets (today+future): {len(condition_ids)}\n"
        f"Threshold (CASH filter): ${threshold:,.0f}\n"
        f"Alert rule: BUY Yes OR SELL No\n"
        f"Mode: LIVE trades after start"
    )

    # ✅ Recap of last 24h (optional)
    if send_recap and condition_ids:
        try:
            send_24h_recap(markets, condition_ids, threshold)
        except Exception as e:
            tg_send(f"⚠️ 24h recap failed: {e}")

    last_refresh = time.time()
    seen = set()

    # Live-only watermark
    start_ts = unix_now()

    while True:
        try:
            if time.time() - last_refresh >= REFRESH_MARKETS_EVERY_SEC:
                title, markets = fetch_active_markets()
                condition_ids = list(markets.keys())
                tg_send(f"🔄 Refreshed markets. Active now: {len(condition_ids)}")
                last_refresh = time.time()

            threshold = float(os.getenv("THRESHOLD_USD", "500000"))

            if not condition_ids:
                time.sleep(poll_seconds)
                continue

            trades = fetch_big_trades(condition_ids, threshold, limit=150)

            for t in trades:
                if (t.get("eventSlug") or "") != EVENT_SLUG:
                    continue
                cid = t.get("conditionId")
                if cid not in markets:
                    continue

                t_ts = int(t.get("timestamp") or 0)
                if t_ts < start_ts:
                    continue

                uid = trade_uid(t)
                if uid in seen:
                    continue

                if increases_yes_exposure(t):
                    meta = markets[cid]
                    cash = float(t.get("price", 0) or 0) * float(t.get("size", 0) or 0)

                    tg_send(
                        "🚨 BIG YES-SIDE TRADE (LIVE)\n"
                        f"{meta.get('question')}\n"
                        f"EndDate: {meta.get('endDate')}\n"
                        f"CASH ≈ ${cash:,.0f}\n"
                        f"Outcome: {t.get('outcome')} | Side: {t.get('side')}\n"
                        f"Time: {ts_to_str(t_ts)}\n"
                        f"Tx: {t.get('transactionHash')}"
                    )

                if t_ts > start_ts:
                    start_ts = t_ts

                seen.add(uid)

            if len(seen) > 30000:
                seen = set(list(seen)[-8000:])

        except Exception as e:
            try:
                tg_send(f"⚠️ Watcher error: {e}")
            except Exception:
                pass

        time.sleep(poll_seconds)

if __name__ == "__main__":
    main()
