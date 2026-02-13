import requests, json
DATA_TRADES = "https://data-api.polymarket.com/trades"
trades = requests.get(DATA_TRADES, params={"limit": 5}, timeout=20).json()
print(json.dumps(trades[0], indent=2))
