"""Deterministic, offline walk-forward baseline runner (research only).

No network, brokerage, AI provider, order placement, or file output.
The caller supplies a local CSV and an explicitly reviewed closure calendar.
A SHA-256 digest identifies the supplied bytes, but does NOT authenticate them.
"""

import argparse
from dataclasses import asdict
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys

from backtesting.fold_summary import summarize_fixed_baseline_folds
from backtesting.historical_data import load_price_bars
from backtesting.walk_forward import (
    build_research_folds,
    evaluate_fixed_baseline_folds,
)


def run_walk_forward_research(
    csv_filename, *, expected_symbol, expected_session_span, closed_sessions,
    train_sessions, test_sessions, embargo_sessions=1, step_sessions=None,
    starting_cash=1000.0, risk_per_trade=0.015, slippage_pct=0.001,
):
    """Return a JSON-compatible, independently restarted fold report.

    An explicit calendar (possibly empty) and exact expected symbol are
    mandatory. Neither is authenticated. The baseline never fits a model
    and training bars are not used to select its parameters.
    """
    if closed_sessions is None:
        raise ValueError("Explicit exchange closure calendar is required")
    if type(expected_symbol) is not str or not expected_symbol:
        raise ValueError("Explicit expected symbol is required")
    if (
        type(expected_session_span) is not tuple
        or len(expected_session_span) != 2
        or any(type(day) is not date for day in expected_session_span)
    ):
        raise ValueError("Explicit research session span is required")
    path = Path(csv_filename)
    # Hash the local input before and after loading. This detects ordinary
    # concurrent edits, not adversarial file replacement or feed forgery.
    digest_before = sha256(path.read_bytes()).hexdigest()
    bars = load_price_bars(path, expected_symbol=expected_symbol)
    digest_after = sha256(path.read_bytes()).hexdigest()
    if digest_before != digest_after:
        raise ValueError("Historical CSV changed during research run")
    folds = build_research_folds(
        bars,
        train_sessions=train_sessions,
        test_sessions=test_sessions,
        embargo_sessions=embargo_sessions,
        step_sessions=step_sessions,
        expected_session_span=expected_session_span,
        closed_sessions=closed_sessions,
    )
    results = evaluate_fixed_baseline_folds(
        folds,
        starting_cash=starting_cash,
        risk_per_trade=risk_per_trade,
        slippage_pct=slippage_pct,
    )
    summary = summarize_fixed_baseline_folds(results, starting_cash=starting_cash)
    return {
        "research_only": True,
        "strategy": "unchanged_opening_range_baseline",
        "data_authenticated": False,
        "source_sha256": digest_before,
        "symbol": expected_symbol,
        "first_session": expected_session_span[0].isoformat(),
        "last_session": expected_session_span[1].isoformat(),
        "closed_sessions": sorted(day.isoformat() for day in closed_sessions),
        "train_sessions": train_sessions,
        "embargo_sessions": embargo_sessions,
        "test_sessions": test_sessions,
        "step_sessions": test_sessions if step_sessions is None else step_sessions,
        "starting_cash": starting_cash,
        "risk_per_trade": risk_per_trade,
        "slippage_pct": slippage_pct,
        "folds": [
            {
                **asdict(result),
                "first_test_date": result.first_test_date.isoformat(),
                "last_test_date": result.last_test_date.isoformat(),
            }
            for result in results
        ],
        "summary": asdict(summary),
        "limitations": (
            "Descriptive independent fold returns only; not a continuous "
            "portfolio, authenticated data, trained AI, or evidence of an edge. "
            "Commissions and other execution costs are not fully modeled."
        ),
    }


def _parse_day(value):
    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("Expected ISO date YYYY-MM-DD") from None
    if day.isoformat() != value:
        raise argparse.ArgumentTypeError("Expected ISO date YYYY-MM-DD")
    return day


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--first-session", required=True, type=_parse_day)
    parser.add_argument("--last-session", required=True, type=_parse_day)
    parser.add_argument(
        "--closed-sessions", required=True,
        help="Comma-separated reviewed exchange closure dates, or 'none'",
    )
    parser.add_argument("--train-sessions", type=int, required=True)
    parser.add_argument("--test-sessions", type=int, required=True)
    parser.add_argument("--embargo-sessions", type=int, default=1)
    parser.add_argument("--step-sessions", type=int)
    parser.add_argument("--starting-cash", type=float, default=1000.0)
    parser.add_argument("--risk-per-trade", type=float, default=0.015)
    parser.add_argument("--slippage-pct", type=float, default=0.001)
    args = parser.parse_args(argv)
    try:
        if args.closed_sessions == "none":
            closures = ()
        else:
            if not args.closed_sessions or any(
                not item for item in args.closed_sessions.split(",")
            ):
                raise ValueError("Invalid closure list")
            closures = tuple(
                _parse_day(item) for item in args.closed_sessions.split(",")
            )
        report = run_walk_forward_research(
            args.csv,
            expected_symbol=args.symbol,
            expected_session_span=(args.first_session, args.last_session),
            closed_sessions=closures,
            train_sessions=args.train_sessions,
            test_sessions=args.test_sessions,
            embargo_sessions=args.embargo_sessions,
            step_sessions=args.step_sessions,
            starting_cash=args.starting_cash,
            risk_per_trade=args.risk_per_trade,
            slippage_pct=args.slippage_pct,
        )
    except (ValueError, OSError, argparse.ArgumentTypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True, indent=2))
    return report


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
