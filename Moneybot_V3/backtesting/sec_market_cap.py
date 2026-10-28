
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


def _valid_positive_number(value):
    """Reject malformed, non-finite, and oversized integer inputs."""
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and value > 0
    except (OverflowError, ValueError):
        return False


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


def _normalize_cik(value):
    """Accept only positive, at-most-ten-digit SEC company identifiers."""
    if type(value) is int:
        if not 0 < value <= 9_999_999_999:
            return None
        return f"{value:010d}"
    if (
        type(value) is str
        and 1 <= len(value) <= 10
        and value.isascii()
        and value.isdecimal()
        and int(value) > 0
    ):
        return value.zfill(10)
    return None


def get_company_cik(symbol):
    """Look up a unique, well-formed US public-company SEC identifier."""

    symbol = symbol.strip().upper()

    if not symbol or not symbol.replace("-", "").isalnum():
        raise ValueError("Invalid stock symbol")

    companies = _request_json(SEC_TICKERS_URL)

    if not isinstance(companies, dict):
        raise SECMarketCapError(
            "Unexpected SEC ticker directory"
        )

    # SEC's directory is normally unique by ticker, but a malformed
    # response or duplicate symbol must not arbitrarily select a CIK.
    # Reject even an invalid later duplicate rather than trusting the
    # first matching record.
    matching_ciks = set()
    for company in companies.values():
        if not (
            isinstance(company, dict)
            and isinstance(company.get("ticker"), str)
            and company["ticker"].upper() == symbol
        ):
            continue
        cik = _normalize_cik(company.get("cik_str"))
        if cik is None:
            raise SECMarketCapError(
                f"Invalid SEC company identifier for {symbol}"
            )
        matching_ciks.add(cik)

    if not matching_ciks:
        raise SECMarketCapError(
            f"No SEC company identifier for {symbol}"
        )
    if len(matching_ciks) != 1:
        raise SECMarketCapError(
            f"Conflicting SEC company identifiers for {symbol}"
        )
    return matching_ciks.pop()


def _canonical_sec_date(value):
    """Require the SEC's canonical YYYY-MM-DD dates, not ISO week/compact dates."""
    if type(value) is not str:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def get_reported_shares_outstanding(symbol):
    """Return recent SEC-reported shares and observation date."""

    cik = get_company_cik(symbol)

    facts = _request_json(
        SEC_COMPANY_FACTS_URL.format(cik=cik)
    )

    # A successful CIK-specific HTTP request does not establish that the
    # returned payload belongs to that company. Bind the SEC facts to the
    # ticker's independently resolved CIK before using any share counts.
    if not isinstance(facts, dict) or _normalize_cik(facts.get("cik")) != cik:
        raise SECMarketCapError(
            f"SEC company facts identifier mismatch for {symbol}"
        )

    try:
        observations = (
            facts["facts"]["dei"][SHARES_TAG]["units"]["shares"]
        )
    except (KeyError, TypeError):
        raise SECMarketCapError(
            f"No SEC shares-outstanding facts for {symbol}"
        ) from None

    if type(observations) is not list:
        raise SECMarketCapError(
            f"Malformed SEC shares-outstanding observations for {symbol}"
        )

    today = date.today()
    earliest = today - timedelta(days=180)

    candidates = []

    for observation in observations:
        if not isinstance(observation, dict):
            continue

        observation_date = _canonical_sec_date(observation.get("end"))
        filed_date = _canonical_sec_date(observation.get("filed"))
        shares = observation.get("val")
        if (
            observation_date is None
            or filed_date is None
            or not _valid_positive_number(shares)
            or not earliest <= observation_date <= today
            or filed_date > today
            or filed_date < observation_date
        ):
            # An SEC filing cannot predate the observation it reports.
            # Treat impossible chronology as unverified, not as evidence.
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

    # Company facts may contain multiple records for the same as-of and
    # filing dates. Conflicting share counts are ambiguous: choosing the
    # first API record could invent a market-cap estimate.
    matching_values = {
        value for end, filed, value in candidates
        if end == observation_date and filed == filed_date
    }
    if len(matching_values) != 1:
        raise SECMarketCapError(
            f"Conflicting SEC shares-outstanding data for {symbol}"
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

    if not _valid_positive_number(share_price):
        raise ValueError("Share price must be positive")

    report = get_reported_shares_outstanding(symbol)
    estimated_cap = report["shares_outstanding"] * float(share_price)
    if not math.isfinite(estimated_cap) or estimated_cap <= 0:
        raise SECMarketCapError("Non-finite SEC market-cap estimate")

    return {
        **report,
        "share_price": float(share_price),
        "estimated_market_cap": estimated_cap,
        "estimate_only": True,
    }
