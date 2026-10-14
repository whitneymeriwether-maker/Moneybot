
"""Download historical SPY minute bars for Moneybot V3 research.

Read-only market data. No trading or broker order requests.
"""

import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json


DATA_URL = "https://data.alpaca.markets/v2/stocks/bars"

START = "2026-09-01T00:00:00Z"
END = "2026-10-01T00:00:00Z"
SYMBOL = "SPY"


def download_history():
    key = os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY")

    if not key or not secret:
        raise RuntimeError(
            "Missing Alpaca market-data credentials. "
            "Use GitHub Actions secrets, not hardcoded keys."
        )

    output = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "SPY_1min_2026_09.csv"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    bars = []
    next_page_token = None

    while True:
        params = {
            "symbols": SYMBOL,
            "timeframe": "1Min",
            "start": START,
            "end": END,
            "limit": 10000,
            "feed": "iex",
            "adjustment": "raw",
        }

        if next_page_token:
            params["page_token"] = next_page_token

        url = DATA_URL + "?" + urlencode(params)

        request = Request(
            url,
            headers={
                "APCA-API-KEY-ID": key,
                "APCA-API-SECRET-KEY": secret,
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except (HTTPError, URLError) as error:
            raise RuntimeError(
                "Historical data download failed"
            ) from error

        bars.extend(payload.get("bars", {}).get(SYMBOL, []))
        next_page_token = payload.get("next_page_token")

        if not next_page_token:
            break

    if not bars:
        raise RuntimeError("Alpaca returned no historical price bars")

    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            ["timestamp", "open", "high", "low", "close", "volume"]
        )

        for bar in bars:
            timestamp = datetime.fromisoformat(
                bar["t"].replace("Z", "+00:00")
            ).astimezone(timezone.utc)

            writer.writerow([
                timestamp.isoformat(),
                bar["o"],
                bar["h"],
                bar["l"],
                bar["c"],
                bar["v"],
            ])

    print(f"Downloaded {len(bars)} bars to {output}")


if __name__ == "__main__":
    download_history()
