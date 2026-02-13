import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

EVENT_SLUG = "us-strikes-iran-by"

GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
DATA_TRADES = "https://data-api.polymarket.com/trades"

def tg_send(text: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    chat_id = os.environ["TELEGRAM_CHAT_ID"].strip()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=20)
    r.raise_for_status()

def notional_usd(trade: dict) -> float:
    # typical: price in [0,1], size = shares. Notional ≈ price * size
    price = float(trade.get("price", 0) or 0)
    size = float(trade.get("size", 0) or 0)
    return price * size

def fetch_event_markets():
    r = requests.get(GAMMA_EVENTS, params={"slug": [EVENT_SLUG], "limit": 10}, timeout=20)
    r.raise_for_status()
    events = r.json()
    if not events:
        raise RuntimeError(f"No event found for slug={EVENT_SLUG}")
    ev = events[0]
    markets = ev.get("markets") or []
    # map conditionId -> metadata
    out = {}
    for m in markets:
        cid = m.get("conditionId")
        if not cid:
            continue
        out[cid] = {
            "slug": m.get("slug"),
            "question": m.get("question"),
            "endDate": m.get("endDate"),
        }
    return ev.get("title"), out

def fetch_latest_trades(limit=200):
    # Pull latest trades across the platform and filter locally (efficient for 42 markets).
    r = requests.get(DATA_TRADES, params={"limit": limit}, timeout=20)
    r.raise_for_status()
    return r.json()

def trade_unique_id(t: dict) -> str:
    # Prefer id if present; otherwise build a stable-ish signature
    return str(t.get("id") or f"{t.get('timestamp')}-{t.get('market')}-{t.get('price')}-{t.get('size')}-{t.get('asset')}")

def main():
    threshold = float(os.getenv("THRESHOLD_USD", "500000"))
    poll_seconds = float(os.getenv("POLL_SECONDS", "3"))

    title, markets = fetch_event_markets()
    watched_ids = set(markets.keys())

    tg_send(f"✅ Watcher started\nEvent: {title}\nMarkets: {len(watched_ids)}\nThreshold: ${threshold:,.0f}")

    seen = set()

    while True:
        try:
            # re-load threshold dynamically (so you can change .env and just restart, or edit future)
            threshold = float(os.getenv("THRESHOLD_USD", "500000"))

            trades = fetch_latest_trades(limit=300)

            # IMPORTANT:
            # Data API trade objects typically include a market identifier.
            # We'll accept either "market" or "conditionId" fields.
            for t in trades:
                market_id = t.get("market") or t.get("conditionId")
                if market_id not in watched_ids:
                    continue

                tid = trade_unique_id(t)
                if tid in seen:
                    continue

                n = notional_usd(t)
                if n >= threshold:
                    meta = markets[market_id]
                    # We include fields so you can confirm it's a YES trade.
                    # Next step: we can tighten it to YES-only once we confirm outcome fields in your trades payload.
                    msg = (
                        "🚨 BIG TRADE DETECTED\n"
                        f"{meta['question']}\n"
                        f"EndDate: {meta['endDate']}\n"
                        f"Notional ≈ ${n:,.0f}\n"
                        f"Price: {t.get('price')} | Size: {t.get('size')}\n"
                        f"Side: {t.get('side')} | Asset: {t.get('asset')}\n"
                        f"Time: {t.get('timestamp')}"
                    )
                    tg_send(msg)

                seen.add(tid)

            # bound memory
            if len(seen) > 15000:
                seen = set(list(seen)[-5000:])

        except Exception as e:
            # don't crash; notify once in a while
            try:
                tg_send(f"⚠️ Watcher error: {e}")
            except Exception:
                pass

        time.sleep(poll_seconds)

if __name__ == "__main__":
    main()
