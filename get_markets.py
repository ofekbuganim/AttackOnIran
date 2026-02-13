import requests
import sys

GAMMA = "https://gamma-api.polymarket.com/markets"

def main():
    print("Fetching markets from Gamma API...")

    # We'll try multiple searches because Gamma search behavior can vary.
    searches = [
        "us-strikes-iran-by",
        "US strikes Iran by",
        "Iran by",
        "strikes iran",
    ]

    all_found = []

    for q in searches:
        print(f"\n--- Searching: {q} ---")
        try:
            r = requests.get(GAMMA, params={"limit": 200, "search": q}, timeout=20)
            print("HTTP:", r.status_code)
            r.raise_for_status()
            data = r.json()

            print("Returned items:", len(data))

            # Print a few raw examples so we see what fields exist
            for m in data[:5]:
                print("Example slug:", m.get("slug"), "| question:", m.get("question"))

            # Collect only our series
            for m in data:
                slug = (m.get("slug") or "").lower()
                if "us-strikes-iran-by" in slug:
                    all_found.append(m)

        except Exception as e:
            print("Error:", e)

    # Deduplicate by conditionId
    unique = {}
    for m in all_found:
        cid = m.get("conditionId") or m.get("id") or m.get("slug")
        unique[cid] = m

    all_found = list(unique.values())

    print("\n==============================")
    print("FINAL FILTERED RESULTS:", len(all_found))
    print("==============================")

    if not all_found:
        print("\n❌ No markets found for 'us-strikes-iran-by'.")
        print("Next step: we'll fetch directly from the Polymarket event page using another endpoint.")
        sys.exit(0)

    # Print all matches nicely
    for m in sorted(all_found, key=lambda x: (x.get("question") or "")):
        print(
            f"{m.get('slug')} | {m.get('question')} | conditionId={m.get('conditionId')}"
        )

if __name__ == "__main__":
    main()
