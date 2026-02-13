import requests

BOT_TOKEN = "8507088508:AAHJp6aC-VYIjBDMpFKALdy77QIBgSjIoWM"  # after /revoke

def main():
    # 1) Verify token belongs to the bot you are messaging
    me = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=20).json()
    print("getMe:", me)

    # 2) Read updates
    upd = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", timeout=20).json()
    print("getUpdates:", upd)

    # 3) Extract chat_id if exists
    try:
        chat_id = upd["result"][-1]["message"]["chat"]["id"]
        print("\n✅ YOUR CHAT_ID:", chat_id)
    except Exception:
        print("\n❌ Still no updates. Token or message mismatch.")

if __name__ == "__main__":
    main()
