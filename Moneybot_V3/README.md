# Moneybot V3 — Phase 2 research prototype

**NOT DEPLOYED.** This folder is a standalone, offline, broker-disconnected paper-research component. It does not change V2 or execute orders.

## Implemented
- Deterministic gate for an AI proposal to buy an opening-range breakout, with evidence and thesis required. The advisory entry gate independently verifies that the candidate's timezone-aware market timestamp is within the policy's freshness window relative to the current UTC clock (allowing up to five seconds of future clock skew), even when the caller reports a fresh data age. This does not authenticate the source or replace execution-time revalidation.
- Initial V3 policy: 1.5% equity risk per trade, 3% of starting equity daily realized-loss stop, 50% total notional exposure, 10% peak-equity drawdown pause, 25% overnight exposure, maximum two trading sessions.
- Separate overnight-hold eligibility gate, and basic closed-trade evaluator for AI vs baseline.
- Historical one-position simulator caps notional exposure at 50% of current paper equity and planned entries at 10% of the completed signal minute's observed volume by default (with a post-hoc veto if the next minute's volume cannot support the planned full fill), in addition to cash and stop-distance risk limits. Position sizing accounts for configured adverse slippage at entry and at the planned stop exit; gaps through the stop and unmodeled execution costs can still exceed the nominal risk budget. It rejects nonpositive stop prices, malformed bar volumes, and never assumes an entry or exit fill on a zero-volume minute. The simulator also blocks new entries after realized same-day paper losses reach 3% of starting capital (configurable), resetting at the next New York calendar day. Separately, a configurable 10% closed-trade peak-equity drawdown pause blocks new entries across subsequent sessions until the simulation is restarted; it does not reset each morning. This is a closed-trade entry halt, **not** a guaranteed loss cap: gaps and existing positions can lose more than the threshold, and the simulator's portfolio peak-drawdown pause only uses closed-trade equity, not intratrade mark-to-market values. The entry participation cap uses only already-observed signal-minute volume for sizing, avoiding future-volume-dependent share counts. The post-hoc entry-volume veto is conservative but can still introduce fill-selection bias; neither rule models order-book liquidity or guarantees executable fills. The cap does **not** model partial exit fills, order-book depth, market impact, or full-session liquidity. Opening-range and breakout signals also require traded volume. This is not a live execution guarantee.
- Opening-range signals and direct historical paper fills skip weekends; this is not an exchange-holiday calendar.
- Read-only IEX daily-bar screening sorts API timestamps by actual UTC instants (not offset-dependent ISO strings) and validates the entire returned history for malformed OHLCV or duplicate UTC dates before choosing the latest 20 bars. The SEC/Alpaca provisional market-cap fallback applies the same full-history validation before selecting its latest 20 prices; corrupt older observations now leave the stock DATA UNVERIFIED rather than allowing a provisional estimate. This reduces false recency and hidden invalid-record errors; IEX volume is still partial-market data, not consolidated liquidity.\n- Historical IEX minute-bar downloads reject timestamps outside the requested UTC window and normalize explicit timezone offsets before chronological sorting. Malformed or duplicate instants cannot replace a previously validated CSV. This validates time bounds, **not** market-data completeness, corporate-action adjustments, exchange holidays, or point-in-time provenance.
- The `run_backtest` pipeline now rejects **interior missing regular-session minute bars** by default (`max_regular_gap_minutes=1`), rather than silently scoring trades over missing data. A larger integer tolerance may be passed explicitly for exploratory sparse-feed analysis, but this does not reconstruct missing prices. An optional strict boundary check (`require_full_regular_sessions=True`) also requires each observed weekday session to contain both 9:30 AM and 3:59 PM New York minute bars. The six-month SPY research runner enables this check by default and now also requires its observed regular-session dates to start on April 1, 2026, end on September 30, 2026, and include at least 120 distinct sessions. This rejects severely truncated or mislabeled six-month files. The runner now additionally checks **every expected weekday trading session** in that window against the five scheduled NYSE full-day closures (April 3, May 25, June 19, July 3, and September 7, 2026; [NYSE calendar](https://www.nyse.com/trade/hours-calendars)), rejecting missing interior trading days and unexpected holiday sessions. For the strict six-month SPY runner, an additional opt-in traded-minute check (`require_traded_regular_minutes=True`) rejects any zero-volume regular-session minute even if every timestamp is present, reducing the risk that synthetic price-filled bars masquerade as genuine trade observations. Other exploratory backtests retain the default `False` to accommodate sparse feeds. This check does not verify genuine exchange prints, consolidated volume, or vendor provenance. The 120-session floor remains a coarse secondary check; the explicit calendar expects **126 trading dates**. Other backtests can opt into this check with `closed_sessions`, but without it only endpoints and the minimum count are checked. This calendar is a fixed snapshot, **not** a dynamic exchange schedule; unscheduled closures, zero-volume synthetic bars, corporate actions, and data provenance remain unverified. Early-close sessions outside this six-month window still need schedule-aware boundary checks. IEX-only minute histories may legitimately be sparse; failing closed is preferable to reporting unsupported performance.
- Current IEX daily-bar screening and the SEC/Alpaca provisional market-cap fallback now reject weekend-dated daily records and zero-volume daily records, including older records outside the selected latest 20 bars. A bar with no observed IEX trades cannot independently verify a closing price; these cases fail closed as DATA UNVERIFIED rather than supplying a verified or provisional screening result. This is a data-quality safeguard, not an authenticated exchange calendar or proof of consolidated volume, genuine prints, or point-in-time provenance.
- Historical CSV ingestion now rejects duplicate or unnamed column headers and malformed rows with missing or surplus cells, rather than silently allowing `csv.DictReader` to overwrite columns or ignore extra values. Complete, uniquely named optional metadata columns remain supported. This checks CSV structure, not the truthfulness of vendor prices or volumes.\n- Offline automated unit tests: `python -m pytest -q`.

- FMP market-cap screening now validates every matching symbol record and refuses conflicting or malformed duplicates, rather than silently trusting the first record. Identical duplicates are permitted. A provider response without an as-of timestamp is still **current research data only**, not point-in-time historical evidence.\n- SEC share-count fallback now excludes filings dated before their reported share observation and refuses conflicting share counts for the same latest observation/filing dates. Such ambiguous facts cannot support even a provisional market-cap estimate; the scanner should report DATA UNVERIFIED instead. These checks do not prove the SEC facts or price are point-in-time appropriate for historical backtests.

- SEC ticker-to-CIK resolution now rejects malformed company identifiers and conflicting duplicate ticker entries instead of arbitrarily using the first match. Identical normalized CIK duplicates are accepted. This only validates directory consistency; it does not establish company identity or historical point-in-time correctness.

- The local SQLite ledger now offers a read-only, timestamp-validated `marked_snapshot` for hypothetical equity, unrealized/total PnL, and gross exposure. It requires an exact, fresh, positive price for every open position, rejects marks preceding the position's latest fill, and prevents a snapshot timestamp from preceding any recorded fill. These marks are supplied by the caller and **not authenticated**; the result is a research valuation, not an execution-time risk check or broker balance.

## Still required before autonomous paper operation
1. Connect an AI model using strictly structured output and source-backed, timestamped evidence; don't trust unverified news or social media as facts.
2. Ingest historical point-in-time OHLCV and permitted news; control look-ahead bias, survivorship bias, stock splits, market holidays, and source licensing.
3. Integrate with the persistent Neon paper engine, using atomic account locks and idempotent fills; gate checks must be repeated at execution time.
4. Implement close/hold scheduling, forced liquidation by the second trading session, gap/slippage assumptions, and conservative fail-closed behavior on missing data.
5. Build reproducible walk-forward historical comparisons and shadow paper trials against V2, with realistic costs and uncertainty intervals. This prototype's closed-trade metric is NOT a full backtester.
6. Add alerts, spending controls for AI API usage, and safeguards against prompt injection in retrieved source text.

The validator does not guarantee loss limits when gaps, delayed bars, or simulation assumptions occur. It has no broker code or live order path.

## Historical symbol binding
Downloaded Alpaca research CSVs now include a `symbol` column on every bar. The CSV loader rejects malformed or mixed ticker metadata even in exploratory files; the strict six-month SPY runner additionally requires every row to explicitly identify `SPY`. A renamed or mixed-symbol file cannot silently be scored as SPY. Legacy CSVs without symbol metadata remain usable only when the caller does not request an expected symbol. Previously downloaded unlabelled SPY CSVs must be downloaded again before running the strict SPY study. This binds labels, **not** data-provider authenticity or point-in-time provenance.


## Offline persistent paper ledger prototype (SQLite, not deployed)

The broker-disconnected `paper_ledger.PaperLedger` supports a durable local
cash-only paper account, whole-share hypothetical BUY/SELL fills, exact-cent
fees and average-cost accounting, and atomic, idempotent event IDs. A second
worker/restart cannot apply the same fill twice; conflicting retries, overspending,
short sales, and backdated events fail closed. The ledger does not contact Alpaca,
Neon, a brokerage, or an AI provider. It cannot send orders or spend money.

Example (local research only):

```python
from datetime import datetime, timezone
from paper_ledger import PaperLedger

ledger = PaperLedger("local_paper_research.sqlite3", starting_cash="1000.00")
ledger.record_fill(
    event_id="offline-example-1",
    timestamp=datetime.now(timezone.utc),
    symbol="SPY", side="BUY", quantity=1,
    price="100.00", fee="0.00",
)
print(ledger.snapshot())
```

The caller supplies hypothetical fills; this component does **not** validate
whether a market actually traded at the supplied price, authenticate fills,
enforce the V3 strategy risk gates, mark open positions to market, handle
corporate actions, or connect to the persistent Neon paper engine. It is an
offline transaction/accounting foundation, **not an autonomous paper trader**.
An end-to-end adapter will need execution-time risk rechecks, fill provenance,
session handling, and replay/reconciliation tests before deployment.


## Persistent paper-account consistency checks

Before acknowledging a fill (including an idempotent retry), after applying
a new fill, and when reading an account snapshot, the offline SQLite ledger
checks that cash plus remaining position cost basis minus realized PnL equals
the original paper cash. It also rejects invalid or out-of-range stored
balances and positions. A mismatch fails closed without applying a new fill.
These checks detect many accidental database edits or accounting defects,
but they **do not** independently authenticate historical fills, prevent
coordinated database tampering, mark positions to market, or enforce the
execution-time V3 risk policy. The ledger remains research-only.


## Explicit full-history paper-ledger audit

Call `ledger.audit_history()` to independently replay the SQLite paper fill
records in insertion order and reconcile the resulting cash, positions, and
realized PnL against stored account state. This detects modified or missing
fill records and coordinated balance changes that can evade the lightweight
accounting invariant. The method validates fill structure, chronological
ordering, no-overspend/no-short constraints, and exact-cent average-cost
accounting. It is a read-only, O(number of fills) verification operation,
intended before research reporting or data migration; it is **not** run on
every transaction. The audit cannot detect coordinated alteration of both
the entire history and account state, authenticate market prints, or prove
paper execution. This remains a broker-disconnected research component.
