# V3 research observation journal (offline only)

Moneybot_V3/v3_observation_journal.py is a **local SQLite research checkpoint**,
separate from the cash PaperLedger. It persists immutable, point-in-time
*declared* Alpaca IEX one-minute OHLCV observations. It has **no network calls,
provider credentials, broker imports, simulated fills, or order submission
path**. It is not used by the Render staging server and does not activate
automatic paper trading.

The caller must independently authenticate the market-data provider, its TLS
session, the observation's provenance, and the receipt clock. Supplying the
feed label "alpaca-iex" does **not** establish any of those facts. The journal
cannot distinguish a fabricated observation from a genuine one.

## Prototype guarantees

- A persistent SQLite file is required. An unrelated existing file is never
  silently initialized as an observation journal.
- Each feed, uppercase symbol, and UTC minute is unique. Identical retries
  return False, including after later minutes. Conflicting or out-of-order
  observations fail closed under a SQLite writer reservation. New observations
  must have nondecreasing declared receipt timestamps; equal receipts allow
  batched arrivals. The latest reader also checks the immediately preceding
  row for reversed or corrupt receipt chronology. This is not a full-history
  audit and does not authenticate the provider or receipt clock.
- Only completed 9:30–15:59 New York weekday minutes may be inserted, with
  a caller-declared receipt timestamp 1–3 minutes after the minute starts.
  Holidays and early closes are **not** checked. Missing minutes are not
  reconstructed.
- OHLC prices must be finite, positive, decimal strings or Decimal values
  with at most six fractional digits. Volume must be a bounded nonnegative
  whole-share integer. Zero volume does not establish executable liquidity.
- The latest() reader requires an explicit aware as_of timestamp and rejects
  observations not yet received or more than three minutes old. That clock
  is caller-supplied and unauthenticated.
- Schema checks require the composite primary key. Reads reject malformed
  stored rows. This is not a cryptographic audit or protection against
  coordinated database tampering.

## Synthetic example

    from datetime import datetime, timedelta, timezone
    from v3_observation_journal import PaperObservationJournal

    minute = datetime(2026, 11, 2, 14, 45, tzinfo=timezone.utc)
    journal = PaperObservationJournal("research_observations.sqlite")
    journal.record(
        feed="alpaca-iex", symbol="SPY", minute=minute,
        received_at=minute + timedelta(seconds=70),
        open="500.01", high="500.03", low="500.00", close="500.02",
        volume=1000,
    )
    print(journal.latest(feed="alpaca-iex", symbol="SPY",
                         as_of=minute + timedelta(seconds=80)))

This is a development seam only. Before a worker may generate or record
hypothetical fills, it still needs independently authenticated and clocked
market data, a durable isolated production database (not the free Render
filesystem), a verified exchange calendar, atomic fill-time risk controls,
restart and duplicate-schedule testing, and controlled shadow trials.
No real broker order path is permitted.
