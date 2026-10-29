# Moneybot V3 — Phase 2 research prototype

## Direct scanner chronology (offline research)

The opening-range scanner now independently checks that every supplied bar
has a timezone-aware, UTC-minute-aligned timestamp and that bar instants
increase strictly. Duplicate and reversed minutes fail closed instead of
double-counting traded volume in VWAP or introducing lookahead into a
breakout signal. This applies even when callers bypass the CSV reader and
simulator. These checks do **not** authenticate market-data provenance,
validate an exchange holiday calendar, or establish executable fills.

## Historical signal-to-bar integrity

The offline trade simulator now rejects externally supplied signals whose
timestamp is absent from the provided historical minute-bar tape. When a
signal includes the scanner's entry-price and VWAP fields, both must be finite
and positive, the entry-price must match the observed signal-minute close,
and the close must exceed both the opening-range high and VWAP. Partially
supplied metadata is rejected. Legacy direct-call test signals that provide
neither field remain supported; they do **not** receive the stronger breakout
metadata verification. These checks bind reported signal metadata to the
supplied bars, not to an authenticated exchange feed, and do not prove that
hypothetical fills could have executed.

## Same-minute simulator fill reconciliation

The optional SQLite reconciliation now accepts a completed hypothetical trade
whose BUY and SELL share a **minute-bar timestamp**, as the simulator can
trigger a stop or target within its entry minute. It preserves BUY-before-SELL
insertion order in the audited paper ledger and still rejects exits preceding
entries or overlapping trades. Minute OHLC does not establish subminute price
ordering or executable fills; this change corrects an accounting diagnostic
false rejection, not execution realism or profitability.

## Cash-funded historical report depletion guard

The historical pipeline now rejects any additional completed hypothetical
trade after closed-trade equity reaches exactly zero, even if the later trade
claims zero profit or a recovery. A final trade that loses exactly 100% of
starting capital remains reportable. This protects the descriptive report
against impossible cash-funded histories supplied by external callers; it
does not authenticate fills or prove trading profitability.

## Opt-in pipeline-to-ledger accounting audit

`backtesting.pipeline.run_backtest(..., expected_symbol="SPY", audit_paper_ledger=True)`
now optionally replays its completed historical simulator trades into a
**disposable, independently audited SQLite paper ledger** and attaches the
reconciliation result to `BacktestReport.paper_ledger_audit`. The CSV must
contain matching symbol metadata in every row. The option defaults to `False`,
so ordinary research reports and the six-month SPY runner are unchanged.
It rejects non-cent-representable hypothetical prices/fees rather than
rounding them or presenting a false audit pass; normal slippage settings can
legitimately make the audit inapplicable. The pipeline also rejects a mismatch
between its reported cash/PnL and the independently audited paper fills.
This is a local accounting integration check, **not** independent validation
of vendor market data, hypothetical fill executability, AI integration,
persistent Neon integration, or trading profitability.

## Offline simulator-to-ledger reconciliation (diagnostic only)

`backtesting.ledger_reconciliation.reconcile_closed_simulation` replays
chronologically ordered, non-overlapping `SimulatedTrade` records as
hypothetical BUY/SELL fill pairs into a **temporary, disposable SQLite
ledger**. It independently audits the ledger history and checks exact-cent
realized PnL and ending cash against Decimal arithmetic on the original
trades. It never touches an existing ledger, calls a provider, or submits
broker orders. Example: `reconcile_closed_simulation(trades, symbol="SPY")`.

This bridge **intentionally refuses fractional-cent prices or fees**, which
the historical simulator commonly produces under nonzero slippage or spread
assumptions. It does not round those away, pretend a failed reconciliation
is a failed trading strategy, or silently modify the original backtest.
It is an opt-in accounting diagnostic for cent-representable scenarios,
not a persistent Neon adapter, AI integration, execution-time risk gate,
authentication of hypothetical fills, or evidence of profitability.

**NOT DEPLOYED.** This folder is a standalone, offline, broker-disconnected paper-research component. It does not change V2 or execute orders.

The standalone completed-trade evaluator now requires canonical uppercase ticker identities, explicit-offset RFC 3339 entry/exit timestamps (up to microsecond precision), strictly positive holding durations, and strictly increasing UTC exit instants. A caller cannot reorder a loss behind a later winner to evade the cash-funded insolvency check, or arbitrarily order simultaneous exits. Legacy placeholder timestamps are no longer accepted; supply actual hypothetical fill times. This checks reported metadata and replay ordering only: it does not authenticate fill provenance, enforce position-level affordability, or prove executable market prices.

Independent fold summaries now reject even tolerance-sized negative expected cash balances and require exact unchanged cash when no trades completed. A genuine final 100% loss remains reportable. These are offline accounting-integrity checks, not evidence of strategy profitability.

Historical backtest reports now fail closed on non-finite individual/aggregate PnL, unrepresentable return and trade statistics, and negative cash-funded or intermediate closed-trade equity. These are accounting/reporting sanity checks, not validation of simulated fill realism, market-data authenticity, or strategy profitability.

Historical minute-bar downloads now reject noncanonical provider timestamps before UTC normalization can launder them into valid-looking CSVs. Both the downloader and CSV reader also reject nonzero nanosecond fractions below Python datetime\u0027s microsecond precision; exact zero fractional seconds remain valid. These are timestamp-integrity checks, not evidence of source authenticity or complete market coverage.

## Implemented
- Deterministic gate for an AI proposal to buy an opening-range breakout, with evidence and thesis required. The advisory entry gate independently verifies that the candidate's timezone-aware market timestamp is within the policy's freshness window relative to the current UTC clock (allowing up to five seconds of future clock skew), even when the caller reports a fresh data age. It also rejects reported ages that understate the independently calculated timestamp age by more than five seconds; conservatively older reported ages are permitted. This does not authenticate the source or replace execution-time revalidation.
- Initial V3 policy: 1.5% equity risk per trade, 3% of starting equity daily realized-loss stop, 50% total notional exposure, 10% peak-equity drawdown pause, 25% overnight exposure, maximum two trading sessions.
- The advisory paper-entry gate now requires the same uppercase, bounded ticker format accepted by the persistent paper ledger (rather than approving lowercase or overlong tickers that the ledger would later reject). The configurable market-data age limit is capped at 86,400 seconds to reject nonsensical or overflowing policy durations; the default remains 720 seconds. These are input-integrity checks, not proof that a market-data timestamp is authentic or an execution-time risk gate.
- Separate overnight-hold eligibility gate, and basic closed-trade evaluator for AI vs baseline. The completed-trade evaluator now uses compensated PnL summation and rejects cash-funded replays whose sequential floating-point equity disagrees with reported net PnL by more than half a cent; this prevents numerical cancellation from presenting contradictory cash and return figures.
- Historical one-position simulator caps notional exposure at 50% of current paper equity and planned entries at 10% of the completed signal minute's observed volume by default (with a post-hoc veto if the next minute's volume cannot support the planned full fill), in addition to cash and stop-distance risk limits. Position sizing accounts for configured adverse slippage at entry and at the planned stop exit; gaps through the stop and unmodeled execution costs can still exceed the nominal risk budget. It rejects nonpositive stop prices, malformed bar volumes, and never assumes an entry or exit fill on a zero-volume minute. The simulator also blocks new entries after realized same-day paper losses reach 3% of starting capital (configurable), resetting at the next New York calendar day. Separately, a configurable 10% closed-trade peak-equity drawdown pause blocks new entries across subsequent sessions until the simulation is restarted; it does not reset each morning. This is a closed-trade entry halt, **not** a guaranteed loss cap: gaps and existing positions can lose more than the threshold, and the simulator's portfolio peak-drawdown pause only uses closed-trade equity, not intratrade mark-to-market values. The entry participation cap uses only already-observed signal-minute volume for sizing, avoiding future-volume-dependent share counts. The post-hoc entry-volume veto is conservative but can still introduce fill-selection bias; neither rule models order-book liquidity or guarantees executable fills. The cap does **not** model partial exit fills, order-book depth, market impact, or full-session liquidity. Opening-range and breakout signals also require traded volume. This is not a live execution guarantee.
- Opening-range signals and direct historical paper fills skip weekends; this is not an exchange-holiday calendar.
- Read-only IEX daily-bar screening sorts API timestamps by actual UTC instants (not offset-dependent ISO strings) and validates the entire returned history for malformed OHLCV or duplicate UTC dates before choosing the latest 20 bars. The SEC/Alpaca provisional market-cap fallback applies the same full-history validation before selecting its latest 20 prices; corrupt older observations now leave the stock DATA UNVERIFIED rather than allowing a provisional estimate. This reduces false recency and hidden invalid-record errors; IEX volume is still partial-market data, not consolidated liquidity.\n- Historical IEX minute-bar downloads reject timestamps outside the requested UTC window, malformed/non-string timestamps, and minute bars whose UTC instant is not minute-aligned (including misleading offsets containing seconds). The CSV reader applies the same UTC alignment check. Direct simulator bars/signals and manually constructed walk-forward training/test tapes now enforce UTC-minute alignment as well, so bypassing CSV ingestion cannot admit a locally aligned but UTC-half-minute timestamp. Explicit timezone offsets are normalized before chronological sorting. Invalid or duplicate instants cannot replace a previously validated CSV. This validates time bounds, **not** market-data completeness, corporate-action adjustments, exchange holidays, or point-in-time provenance.
- The `run_backtest` pipeline now rejects **interior missing regular-session minute bars** by default (`max_regular_gap_minutes=1`), rather than silently scoring trades over missing data. A larger integer tolerance may be passed explicitly for exploratory sparse-feed analysis, but this does not reconstruct missing prices. An optional strict boundary check (`require_full_regular_sessions=True`) also requires each observed weekday session to contain both 9:30 AM and 3:59 PM New York minute bars. The six-month SPY research runner enables this check by default and now also requires its observed regular-session dates to start on April 1, 2026, end on September 30, 2026, and include at least 120 distinct sessions. This rejects severely truncated or mislabeled six-month files. The runner now additionally checks **every expected weekday trading session** in that window against the five scheduled NYSE full-day closures (April 3, May 25, June 19, July 3, and September 7, 2026; [NYSE calendar](https://www.nyse.com/trade/hours-calendars)), rejecting missing interior trading days and unexpected holiday sessions. For the strict six-month SPY runner, an additional opt-in traded-minute check (`require_traded_regular_minutes=True`) rejects any zero-volume regular-session minute even if every timestamp is present, reducing the risk that synthetic price-filled bars masquerade as genuine trade observations. Other exploratory backtests retain the default `False` to accommodate sparse feeds. This check does not verify genuine exchange prints, consolidated volume, or vendor provenance. The 120-session floor remains a coarse secondary check; the explicit calendar expects **126 trading dates**. Other backtests can opt into this check with `closed_sessions`, but without it only endpoints and the minimum count are checked. This calendar is a fixed snapshot, **not** a dynamic exchange schedule; unscheduled closures, zero-volume synthetic bars, corporate actions, and data provenance remain unverified. Early-close sessions outside this six-month window still need schedule-aware boundary checks. IEX-only minute histories may legitimately be sparse; failing closed is preferable to reporting unsupported performance.
- Current IEX daily-bar screening and the SEC/Alpaca provisional market-cap fallback now reject weekend-dated daily records and zero-volume daily records, including older records outside the selected latest 20 bars. A bar with no observed IEX trades cannot independently verify a closing price; these cases fail closed as DATA UNVERIFIED rather than supplying a verified or provisional screening result. This is a data-quality safeguard, not an authenticated exchange calendar or proof of consolidated volume, genuine prints, or point-in-time provenance.
- Historical CSV ingestion now rejects duplicate or unnamed column headers and malformed rows with missing or surplus cells, rather than silently allowing `csv.DictReader` to overwrite columns or ignore extra values. Complete, uniquely named optional metadata columns remain supported. This checks CSV structure, not the truthfulness of vendor prices or volumes.\n- Persistent SQLite paper-account consistency checks now reject invalid stored ticker identifiers and zero acquisition basis on positive-share positions, even when other account fields are manipulated to preserve the basic cash/basis/PnL equation. This is an integrity check, not a guarantee against coordinated tampering or a substitute for explicit fill-history audit.
- Offline automated unit tests: `python -m pytest -q`.

- FMP market-cap screening binds returned ticker metadata to ASCII symbols before case normalization. Unicode lookalikes (such as long-s) cannot impersonate a requested ticker, while lowercase ASCII provider symbols remain supported. This is identity consistency checking, not provider authentication.
- FMP market-cap screening now validates every matching symbol record and refuses conflicting or malformed duplicates, rather than silently trusting the first record. Identical duplicates are permitted. A provider response without an as-of timestamp is still **current research data only**, not point-in-time historical evidence.\n- SEC share-count fallback now excludes filings dated before their reported share observation and refuses conflicting share counts for the same latest observation/filing dates. Such ambiguous facts cannot support even a provisional market-cap estimate; the scanner should report DATA UNVERIFIED instead. These checks do not prove the SEC facts or price are point-in-time appropriate for historical backtests.

- SEC ticker-to-CIK resolution now rejects malformed company identifiers and conflicting duplicate ticker entries instead of arbitrarily using the first match. Identical normalized CIK duplicates are accepted. This only validates directory consistency; it does not establish company identity or historical point-in-time correctness.
- SEC company-facts share counts must identify the same normalized CIK as the ticker directory lookup. Missing, malformed, or conflicting company-facts identifiers invalidate the provisional market-cap estimate; this is response-consistency validation, not cryptographic authentication or proof of historical accuracy.

- The local SQLite ledger now offers a read-only, timestamp-validated `marked_snapshot` for hypothetical equity, unrealized/total PnL, and gross exposure. It requires an exact, fresh, positive price for every open position, rejects marks preceding the position's latest fill, and prevents a snapshot timestamp from preceding any recorded fill. These marks are supplied by the caller and **not authenticated**; the result is a research valuation, not an execution-time risk check or broker balance.

- SQLite paper-ledger initialization now refuses to recreate a missing account row, rejects partially missing ledger schemas, and verifies persisted cash/basis/PnL consistency on reopen. These checks detect some corruption but cannot authenticate a coordinated rewrite of stored fills and balances.

- The SQLite paper ledger refuses to initialize a new account inside a pre-existing empty or unrelated SQLite file, in addition to rejecting incomplete ledger schemas and deleted account rows. A genuinely new account must use a database path that does not already exist. This reduces accidental paper-account resets after data loss or path reuse, but does not prevent an attacker from replacing the entire database with a valid-looking ledger or deleting the file before a new initialization.

## Still required before autonomous paper operation
1. Connect an AI model using strictly structured output and source-backed, timestamped evidence; don't trust unverified news or social media as facts.
2. Ingest historical point-in-time OHLCV and permitted news; control look-ahead bias, survivorship bias, stock splits, market holidays, and source licensing.
3. Integrate with the persistent Neon paper engine, using atomic account locks and idempotent fills; gate checks must be repeated at execution time.
4. Implement close/hold scheduling, forced liquidation by the second trading session, gap/slippage assumptions, and conservative fail-closed behavior on missing data.
5. Build reproducible walk-forward historical comparisons and shadow paper trials against V2, with realistic costs and uncertainty intervals. This prototype's closed-trade metric is NOT a full backtester.
6. Add alerts, spending controls for AI API usage, and safeguards against prompt injection in retrieved source text.

The validator does not guarantee loss limits when gaps, delayed bars, or simulation assumptions occur. It has no broker code or live order path.

## Historical symbol binding
Read-only current IEX quote and daily-bar requests also reject response-level or per-record ticker metadata that contradicts the requested symbol. Alpaca quote prices and daily/minute OHLCV fields must be JSON numbers, not booleans or numeric strings. Invalid provider types fail closed before a stock is approved or a historical CSV is replaced. Optional symbol metadata may be absent, so these checks detect explicit inconsistencies only; they do not authenticate the feed or verify historical provenance.

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

## Offline chronological research folds (not a trained model)

`backtesting.walk_forward.build_research_folds` creates separate training,
embargo, and non-overlapping out-of-sample test windows by complete NYSE
regular trading session. Each observed session must contain 390 consecutive
minute-aligned bars with traded volume and valid OHLC prices. Pass
`expected_session_span` and `closed_sessions` to also reject wholly missing
weekdays; without a verified exchange calendar, an absent entire session
cannot be detected. Early-close sessions are deliberately unsupported.

`evaluate_fixed_baseline_folds` runs the unchanged opening-range simulator
**only on each fold's test bars**. Because folds are public data objects, the
baseline evaluator also requires increasing fold identifiers and chronological, disjoint test windows, and independently revalidates **both training and test** minute tapes for chronology, all 390
minute slots per session, positive traded volume, finite consistent OHLC,
and strict train/embargo/test date ordering before reporting results. This
rejects malformed or manually forged training/test tapes; it does not authenticate
prices, provider provenance, corporate actions, or exchange calendars.
Every fold starts with independent hypothetical capital; fold returns are not a continuous compounded portfolio
or evidence of strategy profitability. The training and embargo portions are
not used to tune a model. This is infrastructure for future reproducible
walk-forward comparisons, **not** completed point-in-time validation, AI
integration, or autonomous paper trading. No network or brokerage access.

## Independent fold summaries (offline)

`backtesting.fold_summary.summarize_fixed_baseline_folds` reports the mean,
median, worst, and best **per-fold** out-of-sample return, plus counts of
signals, trades, positive folds, and zero-return folds. It requires disjoint,
chronological test windows, increasing fold identifiers, finite results, and
cash/PnL/return reconciliation against a common explicit starting balance.
Pass `starting_cash` when the evaluator used anything other than $1,000.

Each fold restarts with fresh hypothetical capital. **Do not add the fold PnLs,
compound fold returns, or interpret a positive mean as proof of an edge.**
The summary is descriptive, not a portfolio equity curve, confidence interval,
AI comparison, or verified market-data result. Source provenance, real costs,
and shadow paper trials remain outstanding.


## Offline reproducible walk-forward runner

Run the fixed, untrained opening-range baseline against a **local** CSV with
explicit symbol binding, a reviewed weekday closure calendar, and complete
390-minute traded sessions. For example, from `Moneybot_V3`:

```bash
python -m backtesting.run_walk_forward \
  --csv data/SPY_1min_2026_04_to_09.csv \
  --symbol SPY --first-session 2026-04-01 --last-session 2026-09-30 \
  --closed-sessions 2026-04-03,2026-05-25,2026-06-19,2026-07-03,2026-09-07 \
  --train-sessions 40 --embargo-sessions 1 --test-sessions 10
```

The command prints machine-readable JSON containing input SHA-256, exact
configuration, per-fold results, and descriptive independent-fold summary.
For a repeatable study, optionally pass `--expected-sha256` followed by the
64-character lowercase hex digest of the reviewed CSV. The runner then fails
closed if the local bytes do not match that pinned digest, before parsing or
scoring. The JSON report records both the observed digest and the optional
expected digest. This prevents accidental dataset substitution but cannot
prove the data came from an exchange or was available at the claimed time.
The hash supports reproducibility checks **only**; it does not authenticate
the feed or prove point-in-time data provenance. Supply `--closed-sessions none`
only for a reviewed span with no weekday closures. Missing whole sessions,
invalid OHLCV, wrong symbols, and unsupported early closes fail closed. The
runner does not fetch data, fit a model, send orders, connect to a brokerage,
or write results to a service. Fixed hypothetical commissions, assumed
spread, and slippage can be configured, but many execution costs remain
unmodeled. No profitable edge or operational readiness is implied.

## Walk-forward test-session coverage disclosure

The offline `run_walk_forward.py` JSON report now includes
`evaluation_coverage`: the number of input trading sessions, the number
actually scored out of sample, the fraction scored, the first and last
test dates, and the explicit list of **untested** session dates. These
untested dates include initial training/embargo sessions, any gaps created
by `--step-sessions` greater than `--test-sessions`, and leftover
sessions that cannot form a complete fold. The report's overall
`first_session`/`last_session` describe the CSV validation window,
**not** the out-of-sample performance window. The coverage fraction
measures which dates were scored; it does not certify data authenticity,
statistical significance, model quality, or trading profitability.


## Predeclared adverse-slippage walk-forward stress (offline)

The local walk-forward runner accepts an optional
`--stress-slippage-pcts 0.002,0.005` flag. These fractions represent
**0.2% and 0.5% adverse slippage per fill**, respectively, versus the
default baseline of 0.1% per fill. Supply at most five strictly increasing
finite fractions, each greater than the selected `--slippage-pct` and
less than 1 minus half the assumed full spread fraction. This is a
*predeclared cost sensitivity check*, not a strategy
optimizer. The runner rejects duplicate, cheaper, unsorted, and invalid
scenarios rather than selecting whichever assumption looks most profitable.

The JSON report's `slippage_stress` array contains independent per-fold
results and descriptive summaries for each assumption. All scenarios use
the same validated historical tape, fold boundaries, strategy, starting
capital, and risk-per-trade setting. Slippage affects share sizing, entry
eligibility, and hypothetical exits, so the number of trades can change
between scenarios; returns need not change monotonically. An empty array
means no stress scenarios were requested. The primary `folds` and
`summary` remain the original baseline.

These tests can include fixed per-share commissions and a constant assumed
full spread, but **do not** model actual spread dynamics, borrow costs,
market impact, partial fills, or execution queue position. They do not
authenticate the CSV or prove an investable edge. Stress comparisons are
descriptive, not confidence intervals, independently verified market
execution, or permission to trade real funds.


## Fixed per-share commission sensitivity (offline only)

The simulator and walk-forward runner accept a hypothetical nonnegative
`commission_per_share` (CLI: `--commission-per-share 0.01`, meaning **$0.01
per share on each side**). Entry affordability and the position's planned-stop
risk include both entry and anticipated exit commission. Recorded hypothetical
cash, realized daily loss and closed-trade drawdown account for fees; fold
`net_pnl` and `return_pct` subtract both entry and exit fees. The JSON
report records the chosen dollar amount, which is also held constant across
all adverse-slippage stress scenarios. The default of zero preserves the
prior no-commission baseline for reproducibility.

This is a deliberately simplified fixed-per-share fee model, not a claim
about a broker's actual fee schedule or exchange rebates. It does not
model bid-ask spread dynamics, regulatory minimums, variable fees, market
impact, queue priority, partial fills, or financing. A modeled stop or
end-of-day exit requires observed minute volume sufficient for the full
hypothetical exit at the configured participation cap. It does not authenticate
historical prices or demonstrate positive out-of-sample performance.

## Assumed bid-ask spread sensitivity (offline only)

The historical simulator and walk-forward runner now accept a nonnegative
hypothetical **full** bid-ask spread fraction (CLI: `--spread-pct 0.004`
means a 0.4% full spread). OHLC bars are **assumed to represent midpoint
prices**, and half the spread is charged on the buy entry and half on the
sell exit, in addition to the selected adverse slippage and fixed per-share
commission. The entry and exit adjustments are additive: a 0.4% full spread
plus 0.1% slippage means a 0.3% adverse adjustment on each side. Position
affordability, planned-stop sizing, and realized PnL reflect these costs.
The JSON field `assumed_full_spread_pct` records the chosen assumption.
All adverse-slippage scenarios retain the same spread assumption. The
default zero spread preserves prior baseline results.

Invalid, nonfinite, negative, or 100%-plus full spread assumptions fail
closed; the combined adverse slippage and half spread must be less than 100%
on either side. **These are not observed bid/ask quotes.** Historical OHLC
may represent trades rather than midpoints, and actual spreads change with
liquidity and time. The constant-spread sensitivity check cannot establish
executable fills, reliable market impact, or profitable trading. No broker
connection or live order path is introduced.

## Fail-closed paper exit participation check

The offline historical simulator now applies `max_participation` to **exits**
as well as entries. If a planned full stop, target, end-of-day, session-end,
or data-end exit would exceed the observed exit minute's traded volume times
that limit, the simulation raises an error instead of recording an
unfillable profitable (or loss-limiting) paper exit. This is intentionally
conservative: it invalidates the scenario rather than guessing partial
fills, deferred stops, or subsequent prices. A valid volume ratio is **not**
evidence of actual executable liquidity, queue priority, bid/ask depth, or
real-world stop execution. It can also reject studies that would otherwise
produce results; do not selectively discard rejected scenarios when
reporting performance. No real orders or brokerage connection are involved.


## Configurable paper volume-participation ceiling (offline only)

The walk-forward runner now accepts `--max-participation 0.025` to cap each
hypothetical **full** entry or exit at 2.5% of its minute's observed traded
share volume (default 10%). The exact fraction is included in the JSON
report and held constant across baseline and adverse-slippage scenarios.
The fixed-baseline fold evaluator accepts the same keyword directly. Invalid,
nonfinite, zero, or greater-than-100% participation settings fail closed.

This is a volume feasibility assumption, **not** proof of executable quotes,
order-book depth, fill priority, or sufficient liquidity. Entry sizes are
based on completed signal-minute volume; the next minute's volume can only
veto an entry. Exits that fail the configured ceiling invalidate the entire
research scenario rather than assuming partial fills. More restrictive caps
can therefore cause a study to fail, and such failures must not be silently
excluded from reported comparisons. No broker, live orders, or spending.


### Daily screening sample continuity (research-only)

Both the primary Alpaca IEX candidate screen and the provisional SEC market-cap
fallback now reject a 20-bar daily sample containing a gap of more than seven
calendar days between successive observed trading dates. A fresh final daily
bar cannot make much older volume observations a recent 20-session average.
These conservative failures are treated as missing/unverified market data,
not as evidence that a stock fails a market-wide liquidity requirement.
The seven-day heuristic permits ordinary weekends and short closures; it is
**not** an authenticated exchange calendar, does not catch every missing
session, and does not establish consolidated liquidity or price provenance.

### Daily provider request-window binding (research-only)

The read-only Alpaca IEX daily-bar downloader now checks each returned bar
against the requested UTC calendar-date range before returning it to the
screening pipeline. A provider response containing an older or future date
fails closed, even if the last twenty records appear plausible. Daily bars
are session-dated, so the first requested date is inclusive despite the
intraday time in the API query; timestamps more than five minutes in the
future are also rejected. This is a response-consistency check, **not**
independent market-data authentication, proof of complete exchange sessions,
or a consolidated-volume guarantee.

## Consistent net-of-cost trade reporting

The six-month offline SPY command-line runner now prints each trade's P/L
using the same net-of-entry-and-exit-commission calculation as the pipeline
and walk-forward evaluator. It explicitly discloses its default hypothetical
0.10% per-side slippage, $0 commission, and zero assumed full spread.
Those defaults are **not** verified transaction costs or executable fills.

## Net-of-cost pipeline accounting

The offline `backtesting.pipeline.run_backtest` accepts optional
`commission_per_share`, `spread_pct`, and `max_participation` settings,
which are passed to the same historical paper simulator used by the
walk-forward evaluator. Reported net profit, ending cash, win/loss counts,
profit factor, and closed-trade drawdown now deduct **both entry and exit
commissions** rather than treating gross price changes as realized PnL.
The default commission and spread remain zero, so callers must explicitly
supply reviewed hypothetical costs; these are not observed executable quotes.
Volume participation is only a conservative bar-volume proxy, not proof of
fillability, partial fills, market impact, or live trading readiness.

## Dated FMP market-cap screening observations (research only)

The current FMP market-cap endpoint returns a reported trading date with each
capitalization value. V3 now requires a canonical `YYYY-MM-DD` date no more
than seven UTC calendar days old and never in the future. Every matching
record must have a finite positive market cap and a valid date; multiple
matching records must agree on both the capitalization and observation date.
Missing, stale, malformed, future-dated, or conflicting values are treated as
unavailable provider evidence, so the scanner may attempt its **provisional**
SEC/Alpaca estimate rather than reporting a verified market-cap pass.
The seven-day limit tolerates weekends and short closures but is not an
authenticated exchange calendar. A recent provider-reported date does not
authenticate its source, confirm the market cap's accuracy, or establish
point-in-time historical validity. No brokerage orders or spending are enabled.


## SEC share-observation input integrity (research only)

The provisional SEC market-cap estimator now requires the company-facts
`units.shares` collection to be a JSON list and accepts only canonical
`YYYY-MM-DD` observation and filing dates. Malformed date entries are
ignored, while a malformed collection fails closed with an explicit data
error. This avoids treating compact ISO or week-date representations as
verified SEC observations and prevents unexpected provider shapes from
escaping as unhandled Python exceptions. The SEC/Alpaca estimate remains
provisional: these checks do not authenticate EDGAR data, reconstruct
historical point-in-time shares, or establish trading profitability.


## ASCII ticker identity consistency (research only)

The historical downloader and SEC provisional market-cap lookup share the
same ASCII-only ticker validation. Non-string symbols and Unicode characters
that could turn into different ASCII tickers during uppercasing are rejected
before any provider request. Conventional dotted class-share symbols are
accepted consistently, and SEC company-directory ticker matches must be
ASCII. SEC research reports use the canonical uppercase symbol even when a
caller supplies surrounding whitespace. This is input-identity validation,
not independent authentication of a provider's company mapping or prices.


## Canonical Alpaca research timestamps (read-only)

The IEX quote and recent daily-bar reader now requires RFC 3339 timestamps
with a full calendar date, `T` separator, seconds, and an explicit `Z` or
minute-resolution UTC offset. Alpaca's fractional-second timestamps, including
nanosecond precision, remain accepted. Python's permissive ISO parser could
otherwise accept compact dates, week dates, spaces, or second-level timezone
offsets as apparently valid provider evidence. Invalid timestamps now fail
closed before quote freshness checks or daily-bar sorting. This format check
does not authenticate provider responses, guarantee session completeness, or
establish actual fillability. V3 remains research/paper-only.

## Canonical historical CSV timestamps (research-only)

The offline historical CSV reader now requires canonical RFC 3339 timestamps
with a complete calendar date, T separator, seconds, and an explicit Z or
minute-resolution UTC offset. Optional fractional seconds (up to nine digits)
are permitted only when the minute-bar instant is aligned to a UTC minute.
Python's permissive ISO parser also accepts compact/week dates, spaces,
and second-resolution offsets; those forms are rejected rather than silently
entering backtests. The earlier UTC-minute alignment check remains in place.
This validates timestamp representation, not the authenticity, completeness,
or provenance of historical market data.

Historical CSV whole-share volume tokens must contain only ASCII decimal
digits. The reader rejects signs, whitespace, underscores, Unicode digits,
and exponent notation rather than allowing Python's permissive `int()` parser
to reinterpret malformed research evidence. Leading zeroes remain accepted.
This is a representation check, not proof of observed exchange volume.

- The direct stock screener now validates ASCII ticker identities even when callers bypass the Alpaca downloader/scanner, rejecting Unicode lookalikes and malformed symbols before classifying a numeric pass. Legitimate lowercase ASCII and dotted class-share tickers are normalized to canonical uppercase in results. This is symbol consistency, not provider authentication or permission to trade.

## Cash-funded closed-trade insolvency checks (offline research)

Both the lightweight completed-trade evaluator and the sequential historical
backtester now reject a negative cash-funded equity balance **at the first
insolvent closed trade**, even if later hypothetical trades would recover it.
An exactly zero balance may be reported as a total loss, but does not authorize
subsequent purchases. Both evaluators now explicitly reject any additional
completed trade after an exact zero balance (including purported zero-PnL or
winning trades), and reject malformed trade records instead of crashing on
missing attributes. This is an accounting integrity check, not an intratrade
mark-to-market risk limit, proof of executable fills, or a live-trading control.

## Zero-equity paper ledger reporting (offline research)

The broker-disconnected SQLite paper ledger's read-only marked snapshot now
supports a fully liquidated account with exactly zero remaining cash. Such an
account has no open positions or market exposure, so its gross exposure is
reported as 0.0000% without dividing by zero; realized and total losses remain
visible. The existing checks for extra/missing marks, backdated snapshots,
insufficient cash for further hypothetical buys, and accounting integrity
remain in force. This is a terminal accounting edge case, not permission for
margin trading, new capital, broker orders, or deployment.

### Complete opening-range signal provenance (offline)

For simulator inputs with full entry-price/VWAP metadata and all 15 traded
9:30–9:44 a.m. New York opening-range minutes, the simulator now independently
regenerates the opening-range breakout signal from the supplied OHLCV bars.
A changed opening-range high/low, understated VWAP, fabricated breakout, or
wrong signal minute fails validation instead of changing paper results.
Short legacy direct-call tapes without the full opening range remain supported;
this check does not authenticate the underlying historical data or fills.

### Complete opening-range signal provenance

When all 15 traded opening-range minutes are supplied, externally supplied
signals must include both observed entry-price and VWAP metadata so the
simulator can independently reconcile the signal with the historical scanner.
Omitting those fields is no longer a way to bypass opening-range provenance.
Short legacy direct-call tapes without the complete opening range retain their
limited backward-compatible behavior; those tapes cannot authenticate the
missing opening-range observations. This remains hypothetical, paper-only
research and does not establish executable fills or market-data authenticity.

### External signal session boundaries (offline research)

The direct historical simulator now rejects externally supplied breakout
signals outside 9:45 a.m.–3:59 p.m. New York time on weekdays. Previously,
short legacy tapes could inject a premarket or unfinished-opening-range signal
and simulate a next-minute entry even though the opening range had not closed.
The final 3:59 p.m. signal remains valid scanner output but cannot fill after
the 4:00 p.m. regular-session close. This guards signal chronology; it does
not verify exchange holidays, market data, or executable orders.

### Complete daily-bar chronology (offline research)

Before using IEX daily bars to screen a stock or to form a provisional
SEC/Alpaca market-cap estimate, V3 now verifies that the **entire** supplied
history is strictly chronological. An out-of-order older observation can no
longer hide outside the latest 20-bar continuity sample and distort which
sessions are used. The read-only downloader already sorts provider responses;
this additionally protects direct callers and injected research datasets.
It does not independently authenticate exchange timestamps, consolidated
volume, historical prices, or the data provider.

## Direct simulator share-volume precision

The broker-disconnected historical simulator now applies the same maximum
exact whole-share count (2^53 - 1) as the CSV loader and walk-forward folds,
even when callers pass in-memory bars directly. Larger counts are rejected
before participation-based sizing can round or misrepresent volume. Zero-volume
non-signal bars remain supported for sparse exploratory tapes. This is an
input-integrity safeguard, not a verification of genuine exchange volume,
market liquidity, executable fills, or strategy profitability.
