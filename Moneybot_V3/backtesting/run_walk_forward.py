"""Deterministic, offline walk-forward baseline runner (research only).

No network, brokerage, AI provider, order placement, or file output.
The caller supplies a local CSV and an explicitly reviewed closure calendar.
A SHA-256 digest identifies the supplied bytes, but does NOT authenticate them.
"""

import argparse
from dataclasses import asdict
from datetime import date
from hashlib import sha256
from math import isfinite
import json
import re
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from backtesting.fold_summary import summarize_fixed_baseline_folds
from backtesting.historical_data import load_price_bars
from backtesting.walk_forward import (
    build_research_folds,
    evaluate_fixed_baseline_folds,
)


def _finite_real(value):
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


def run_walk_forward_research(
    csv_filename, *, expected_symbol, expected_session_span, closed_sessions,
    train_sessions, test_sessions, embargo_sessions=1, step_sessions=None,
    starting_cash=1000.0, risk_per_trade=0.015, slippage_pct=0.001,
    expected_sha256=None, stress_slippage_pcts=(),
    commission_per_share=0.0, spread_pct=0.0,
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
    if expected_sha256 is not None and (
        type(expected_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
    ):
        raise ValueError("Expected SHA-256 must be 64 lowercase hex characters")
    if (
        type(slippage_pct) not in (int, float)
        or not isfinite(slippage_pct)
        or not 0 <= slippage_pct < 1
    ):
        raise ValueError("Invalid baseline slippage")
    if (
        not _finite_real(commission_per_share)
        or commission_per_share < 0
    ):
        raise ValueError("Invalid commission per share")
    if not _finite_real(spread_pct) or not 0 <= spread_pct < 1:
        raise ValueError("Invalid assumed spread")
    if slippage_pct + spread_pct / 2 >= 1:
        raise ValueError("Combined slippage and spread must be below 100%")
    # Predeclare adverse scenarios. No retrospective selection of a
    # best-performing assumption, and no scenarios cheaper than baseline.
    if type(stress_slippage_pcts) is not tuple or len(stress_slippage_pcts) > 5:
        raise ValueError("Stress slippage must be a tuple of at most five values")
    previous_slippage = slippage_pct
    for stress_slippage in stress_slippage_pcts:
        if (
            type(stress_slippage) not in (int, float)
            or not isfinite(stress_slippage)
            or not previous_slippage < stress_slippage < 1 - spread_pct / 2
        ):
            raise ValueError(
                "Stress slippage must be finite, strictly increasing, "
                "and greater than baseline"
            )
        previous_slippage = stress_slippage
    path = Path(csv_filename)
    # Hash the local input before and after loading. This detects ordinary
    # concurrent edits, not adversarial file replacement or feed forgery.
    digest_before = sha256(path.read_bytes()).hexdigest()
    if expected_sha256 is not None and digest_before != expected_sha256:
        raise ValueError("Historical CSV SHA-256 does not match expected digest")
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
        commission_per_share=commission_per_share,
        spread_pct=spread_pct,
    )
    summary = summarize_fixed_baseline_folds(results, starting_cash=starting_cash)
    stress_reports = []
    for adverse_slippage in stress_slippage_pcts:
        adverse_results = evaluate_fixed_baseline_folds(
            folds,
            starting_cash=starting_cash,
            risk_per_trade=risk_per_trade,
            slippage_pct=adverse_slippage,
            commission_per_share=commission_per_share,
        spread_pct=spread_pct,
        )
        adverse_summary = summarize_fixed_baseline_folds(
            adverse_results, starting_cash=starting_cash
        )
        stress_reports.append({
            "slippage_pct": adverse_slippage,
            "folds": [
                {
                    **asdict(result),
                    "first_test_date": result.first_test_date.isoformat(),
                    "last_test_date": result.last_test_date.isoformat(),
                }
                for result in adverse_results
            ],
            "summary": asdict(adverse_summary),
        })
    # A successful fold run need not score every input session. Initial
    # training/embargo dates, step gaps, and a trailing incomplete window
    # are intentionally not out-of-sample observations. Report them rather
    # than letting the requested CSV span imply full test coverage.
    observed_dates = sorted({
        bar.timestamp.astimezone(ZoneInfo("America/New_York")).date()
        for bar in bars
    })
    tested_dates = {day for fold in folds for day in fold.test_dates}
    untested_dates = [day for day in observed_dates if day not in tested_dates]
    return {
        "research_only": True,
        "strategy": "unchanged_opening_range_baseline",
        "data_authenticated": False,
        "source_sha256": digest_before,
        "expected_source_sha256": expected_sha256,
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
        "commission_per_share": commission_per_share,
        "assumed_full_spread_pct": spread_pct,
        "evaluation_coverage": {
            "observed_session_count": len(observed_dates),
            "tested_session_count": len(tested_dates),
            "untested_session_count": len(untested_dates),
            "tested_session_fraction": len(tested_dates) / len(observed_dates),
            "first_test_session": min(tested_dates).isoformat(),
            "last_test_session": max(tested_dates).isoformat(),
            "untested_session_dates": [day.isoformat() for day in untested_dates],
        },
        "folds": [
            {
                **asdict(result),
                "first_test_date": result.first_test_date.isoformat(),
                "last_test_date": result.last_test_date.isoformat(),
            }
            for result in results
        ],
        "summary": asdict(summary),
        "slippage_stress": stress_reports,
        "limitations": (
            "Descriptive independent fold returns only; not a continuous "
            "portfolio, authenticated data, trained AI, or evidence of an edge. "
            "Unscored training, embargo, step-gap, and tail sessions are "
            "listed in evaluation_coverage. Commissions and other execution "
            "costs beyond the specified fixed per-share commission, assumed "
            "full bid-ask spread, and slippage are not fully modeled. The "
            "spread is an assumption applied to midpoint OHLC, not measured "
            "quotes or proof of executable fills. Adverse slippage scenarios rerun "
            "position sizing and fills independently, so trade counts can "
            "change; they are not a confidence interval or an edge claim."
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
    parser.add_argument(
        "--expected-sha256",
        help="Optional pinned lowercase SHA-256 of the local CSV bytes",
    )
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
    parser.add_argument(
        "--spread-pct", type=float, default=0.0,
        help="Assumed full bid-ask spread fraction; half charged on each side",
    )
    parser.add_argument(
        "--commission-per-share", type=float, default=0.0,
        help="Hypothetical dollar commission per share on EACH fill side",
    )
    parser.add_argument(
        "--stress-slippage-pcts",
        help="Optional increasing adverse slippage fractions, e.g. 0.002,0.005 (max five)",
    )
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
        if args.stress_slippage_pcts is None:
            stresses = ()
        else:
            values = args.stress_slippage_pcts.split(",")
            if any(not value.strip() for value in values):
                raise ValueError("Invalid stress slippage list")
            try:
                stresses = tuple(float(value) for value in values)
            except ValueError:
                raise ValueError("Invalid stress slippage list") from None
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
            commission_per_share=args.commission_per_share,
            spread_pct=args.spread_pct,
            expected_sha256=args.expected_sha256,
            stress_slippage_pcts=stresses,
        )
    except (ValueError, OSError, argparse.ArgumentTypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True, indent=2))
    return report


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
