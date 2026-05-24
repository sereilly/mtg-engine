"""Download all cards from the Magic: The Gathering Alpha (LEA) set using the Scryfall API."""

import json
import time
import urllib.request
import urllib.error

BASE_URL = "https://api.scryfall.com/cards/search?q=set%3Alea&order=name"


def fetch_all_lea_cards():
    cards = []
    url = BASE_URL

    while url:
        print(f"Fetching: {url}")
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "MTG-Simulator/1.0",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as e:
            print(f"Error fetching data: {e}")
            break

        cards.extend(data.get("data", []))
        print(f"  Retrieved {len(data.get('data', []))} cards (total: {len(cards)})")

        url = data.get("next_page") if data.get("has_more") else None

        if url:
            time.sleep(0.1)  # Scryfall rate limit: max 10 req/s

    return cards


def main():
    print("Downloading LEA (Alpha) card data from Scryfall...")
    cards = fetch_all_lea_cards()
    print(f"\nTotal cards downloaded: {len(cards)}")

    output_path = "lea_cards.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cards, f, indent=2, ensure_ascii=False)

    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
