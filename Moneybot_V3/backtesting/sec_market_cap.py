
"""SEC shares-outstanding research for Moneybot V3.

Read-only research. Does not place brokerage orders.
Does not modify the existing FMP market-cap provider.
"""

import json
import math
import os
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SEC_TICKERS_URL = (
    "https://www.sec.gov/files/company_tickers.json"
)
SEC_COMPANY_FACTS_URL = (
    "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
)

SHARES_TAG = "EntityCommonStockSharesOutstanding"


class SECMarketCapError(RuntimeError):
    """Raised when reliable SEC share data is unavailable."""


def _request_json(url):
    """Retrieve public SEC JSON without exposing credentials."""

    contact = os.environ.get(
        "SEC_CONTACT_EMAIL",
        "moneybot-research@example.com",
    )

    request = Request(
        url,
        headers={
            "User-Agent": f"MoneybotV3 Research {contact}",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        raise SECMarketCapError(
            f"SEC HTTP {error.code}"
        ) from None
    except URLError:
        raise SECMarketCapError(
            "SEC network connection failed"
        ) from None
    except (ValueError, UnicodeError):
        raise SECMarketCapError(
            "SEC returned invalid JSON"
        ) from None


def get_company_cik(symbol):
    """Look up a US public company's SEC identifier."""

    symbol = symbol.strip().upper()

    if not symbol or not symbol.replace("-", "").isalnum():
        raise ValueError("Invalid stock symbol")

    companies = _request_json(SEC_TICKERS_URL)

    if not isinstance(companies, dict):
        raise SECMarketCapError(
            "Unexpected SEC ticker directory"
        )

    for company in companies.values():
        if (
            isinstance(company, dict)
            and str(company.get("ticker", "")).upper() == symbol
        ):
            return str(company["cik_str"]).zfill(10)

    raise SECMarketCapError(
        f"No SEC company identifier for {symbol}"
    )


def get_reported_shares_outstanding(symbol):
    """Return recent SEC-reported shares and observation date."""

    cik = get_company_cik(symbol)

    facts = _request_json(
        SEC_COMPANY_FACTS_URL.format(cik=cik)
    )

    try:
        observations = (
            facts["facts"]["dei"][SHARES_TAG]["units"]["shares"]
        )
    except (KeyError, TypeError):
        raise SECMarketCapError(
            f"No SEC shares-outstanding facts for {symbol}"
        ) from None

    today = date.today()
    earliest = today - timedelta(days=180)

    candidates = []

    for observation in observations:
        if not isinstance(observation, dict):
            continue

        try:
            observation_date = date.fromisoformat(
                observation["end"]
            )
            filed_date = date.fromisoformat(
                observation["filed"]
            )
            shares = observation["val"]
        except (KeyError, TypeError, ValueError):
            continue

        if (
            isinstance(shares, bool)
            or not isinstance(shares, (int, float))
            or not math.isfinite(shares)
            or shares <= 0
            or not earliest <= observation_date <= today
            or filed_date > today
        ):
            continue

        candidates.append(
            (observation_date, filed_date, float(shares))
        )

    if not candidates:
        raise SECMarketCapError(
            f"No recent SEC shares-outstanding data for {symbol}"
        )

    observation_date, filed_date, shares = max(
        candidates,
        key=lambda item: (item[0], item[1]),
    )

    return {
        "symbol": symbol.upper(),
        "shares_outstanding": shares,
        "observation_date": observation_date.isoformat(),
        "filed_date": filed_date.isoformat(),
        "source": "SEC EDGAR",
    }


def estimate_market_cap(symbol, share_price):
    """Estimate market cap from current price and SEC share count."""

    if (
        isinstance(share_price, bool)
        or not isinstance(share_price, (int, float))
        or not math.isfinite(share_price)
        or share_price <= 0
    ):
        raise ValueError("Share price must be positive")

    report = get_reported_shares_outstanding(symbol)

    return {
        **report,
        "share_price": float(share_price),
        "estimated_market_cap": (
            report["shares_outstanding"] * share_price
        ),
        "estimate_only": True,
    }
