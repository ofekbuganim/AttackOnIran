import requests

EVENT_SLUG = "us-strikes-iran-by"
GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"

r = requests.get(GAMMA_EVENTS, params={"slug": [EVENT_SLUG], "limit": 10}, timeout=20)
r.raise_for_status()
events = r.json()

ev = events[0]
print("Event:", ev.get("title"))
markets = ev.get("markets") or []
print("Markets:", len(markets))

for m in markets:
    print(m.get("slug"), "|", m.get("conditionId"), "|", m.get("endDate"), "|", m.get("question"))
