import os, requests
from dotenv import load_dotenv

load_dotenv()
token = os.environ["TELEGRAM_BOT_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]

r = requests.post(
    f"https://api.telegram.org/bot{token}/sendMessage",
    json={"chat_id": chat_id, "text": "✅ Test push works!"},
    timeout=20
)
r.raise_for_status()
print("Sent!")
