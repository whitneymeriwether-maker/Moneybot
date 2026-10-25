# Moneybot V3 — Phase 2 research prototype

**NOT DEPLOYED.** This folder is a standalone, offline, broker-disconnected paper-research component. It does not change V2 or execute orders.

## Implemented
- Deterministic gate for an AI proposal to buy an opening-range breakout, with evidence and thesis required.
- Initial V3 policy: 1.5% equity risk per trade, 3% of starting equity daily realized-loss stop, 50% total notional exposure, 10% peak-equity drawdown pause, 25% overnight exposure, maximum two trading sessions.
- Separate overnight-hold eligibility gate, and basic closed-trade evaluator for AI vs baseline.
- Historical one-position simulator caps notional exposure at 50% of current paper equity and entries at 10% of observed minute volume by default, in addition to cash and stop-distance risk limits. It rejects nonpositive stop prices, malformed bar volumes, and never assumes an entry or exit fill on a zero-volume minute. The simulator also blocks new entries after realized same-day paper losses reach 3% of starting capital (configurable), resetting at the next New York calendar day. This is a closed-trade entry halt, **not** a guaranteed loss cap: gaps and existing positions can lose more than the threshold, and the simulator does not yet implement the portfolio peak-drawdown pause. The entry participation cap does **not** model partial exit fills, order-book depth, market impact, or full-session liquidity. Opening-range and breakout signals also require traded volume. This is not a live execution guarantee.
- Opening-range signals and direct historical paper fills skip weekends; this is not an exchange-holiday calendar.
- Offline automated unit tests: `python -m pytest -q`.

## Still required before autonomous paper operation
1. Connect an AI model using strictly structured output and source-backed, timestamped evidence; don't trust unverified news or social media as facts.
2. Ingest historical point-in-time OHLCV and permitted news; control look-ahead bias, survivorship bias, stock splits, market holidays, and source licensing.
3. Integrate with the persistent Neon paper engine, using atomic account locks and idempotent fills; gate checks must be repeated at execution time.
4. Implement close/hold scheduling, forced liquidation by the second trading session, gap/slippage assumptions, and conservative fail-closed behavior on missing data.
5. Build reproducible walk-forward historical comparisons and shadow paper trials against V2, with realistic costs and uncertainty intervals. This prototype's closed-trade metric is NOT a full backtester.
6. Add alerts, spending controls for AI API usage, and safeguards against prompt injection in retrieved source text.

The validator does not guarantee loss limits when gaps, delayed bars, or simulation assumptions occur. It has no broker code or live order path.
