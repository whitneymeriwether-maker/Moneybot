"""Offline walk-forward CSV runner tests: no network, orders, or accounts."""
import csv
from datetime import date, datetime, time, timedelta
import hashlib
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtesting.run_walk_forward import main, run_walk_forward_research


NY = ZoneInfo("America/New_York")


def make_csv(tmp_path, *, sessions=6, missing_day=None, symbol="SPY"):
    filename = tmp_path / "bars.csv"
    day = date(2026, 10, 12)
    with filename.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp", "symbol", "open", "high", "low", "close", "volume"])
        for _ in range(sessions):
            while day.weekday() >= 5:
                day += timedelta(days=1)
            if day != missing_day:
                start = datetime.combine(day, time(9, 30), tzinfo=NY)
                for minute in range(390):
                    writer.writerow([
                        (start + timedelta(minutes=minute)).isoformat(),
                        symbol, 100, 101, 99, 100, 1000,
                    ])
            day += timedelta(days=1)
    return filename


def run(filename, **kwargs):
    options = dict(
        expected_symbol="SPY",
        expected_session_span=(date(2026, 10, 12), date(2026, 10, 19)),
        closed_sessions=(),
        train_sessions=3,
        embargo_sessions=1,
        test_sessions=2,
    )
    options.update(kwargs)
    return run_walk_forward_research(filename, **options)


def test_runner_produces_reproducible_json_safe_independent_folds(tmp_path):
    filename = make_csv(tmp_path)
    result = run(filename)
    assert result == run(filename)
    assert result["source_sha256"] == hashlib.sha256(filename.read_bytes()).hexdigest()
    assert result["data_authenticated"] is False
    assert result["research_only"] is True
    assert result["symbol"] == "SPY"
    assert len(result["folds"]) == 1
    assert result["folds"][0]["first_test_date"] == "2026-10-16"
    assert result["folds"][0]["last_test_date"] == "2026-10-19"
    assert result["folds"][0]["net_pnl"] == 0
    assert result["summary"]["fold_count"] == 1
    assert result["evaluation_coverage"] == {
        "observed_session_count": 6,
        "tested_session_count": 2,
        "untested_session_count": 4,
        "tested_session_fraction": 2 / 6,
        "first_test_session": "2026-10-16",
        "last_test_session": "2026-10-19",
        "untested_session_dates": [
            "2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15",
        ],
    }
    assert result["summary"]["mean_fold_return_pct"] == 0
    assert "total_return_pct" not in result["summary"]
    assert json.loads(json.dumps(result)) == result


def test_runner_rejects_missing_entire_session(tmp_path):
    filename = make_csv(tmp_path, missing_day=date(2026, 10, 14))
    with pytest.raises(ValueError, match="calendar mismatch"):
        run(filename)


def test_runner_rejects_wrong_symbol(tmp_path):
    filename = make_csv(tmp_path, symbol="QQQ")
    with pytest.raises(ValueError, match="symbol"):
        run(filename)


def test_runner_rejects_missing_explicit_calendar_and_symbol(tmp_path):
    filename = make_csv(tmp_path)
    with pytest.raises(ValueError, match="calendar"):
        run(filename, closed_sessions=None)
    with pytest.raises(ValueError, match="symbol"):
        run(filename, expected_symbol=None)


@pytest.mark.parametrize("bad", [
    (date(2026, 10, 12),),
    [date(2026, 10, 12), date(2026, 10, 19)],
    (datetime(2026, 10, 12), date(2026, 10, 19)),
])
def test_runner_rejects_invalid_span(tmp_path, bad):
    with pytest.raises(ValueError, match="span"):
        run(make_csv(tmp_path), expected_session_span=bad)


def test_runner_rejects_invalid_closed_day(tmp_path):
    filename = make_csv(tmp_path)
    with pytest.raises(ValueError, match="calendar"):
        run(filename, closed_sessions=(date(2026, 10, 17),))


def test_runner_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        run(tmp_path / "missing.csv")


def test_cli_emits_machine_readable_json(tmp_path, capsys):
    filename = make_csv(tmp_path)
    main([
        "--csv", str(filename), "--symbol", "SPY",
        "--first-session", "2026-10-12",
        "--last-session", "2026-10-19",
        "--closed-sessions", "none",
        "--train-sessions", "3", "--test-sessions", "2",
    ])
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["fold_count"] == 1


@pytest.mark.parametrize("bad_closures", ["", "2026-10-12,", "2026-10-99"])
def test_cli_rejects_malformed_closure_list(tmp_path, bad_closures):
    filename = make_csv(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main([
            "--csv", str(filename), "--symbol", "SPY",
            "--first-session", "2026-10-12",
            "--last-session", "2026-10-19",
            "--closed-sessions", bad_closures,
            "--train-sessions", "3", "--test-sessions", "2",
        ])
    assert exc.value.code == 2


def test_runner_accepts_explicit_pinned_csv_digest(tmp_path):
    filename = make_csv(tmp_path)
    digest = hashlib.sha256(filename.read_bytes()).hexdigest()
    report = run(filename, expected_sha256=digest)
    assert report["source_sha256"] == digest
    assert report["expected_source_sha256"] == digest
    assert run(filename)["expected_source_sha256"] is None


def test_runner_rejects_unexpected_pinned_csv_bytes(tmp_path):
    filename = make_csv(tmp_path)
    with pytest.raises(ValueError, match="does not match expected digest"):
        run(filename, expected_sha256="0" * 64)


@pytest.mark.parametrize("invalid_digest", [
    "", "0" * 63, "g" * 64, "A" * 64, 123, True,
])
def test_runner_rejects_malformed_expected_digest(tmp_path, invalid_digest):
    filename = make_csv(tmp_path)
    with pytest.raises(ValueError, match="Expected SHA-256"):
        run(filename, expected_sha256=invalid_digest)


def test_cli_can_pin_local_input_digest(tmp_path, capsys):
    filename = make_csv(tmp_path)
    digest = hashlib.sha256(filename.read_bytes()).hexdigest()
    arguments = [
        "--csv", str(filename), "--symbol", "SPY",
        "--first-session", "2026-10-12",
        "--last-session", "2026-10-19",
        "--closed-sessions", "none",
        "--train-sessions", "3", "--test-sessions", "2",
        "--expected-sha256", digest,
    ]
    main(arguments)
    assert json.loads(capsys.readouterr().out)["expected_source_sha256"] == digest
    with pytest.raises(SystemExit) as exc:
        main(arguments[:-1] + ["0" * 64])
    assert exc.value.code == 2


def test_runner_discloses_skipped_step_sessions_and_incomplete_tail(tmp_path):
    filename = make_csv(tmp_path, sessions=10)
    report = run(
        filename,
        expected_session_span=(date(2026, 10, 12), date(2026, 10, 23)),
        step_sessions=3,
    )
    # Starts at session offsets 0 and 3. The final two input sessions
    # cannot form a third full training/embargo/test fold.
    assert len(report["folds"]) == 2
    coverage = report["evaluation_coverage"]
    assert coverage["observed_session_count"] == 10
    assert coverage["tested_session_count"] == 4
    assert coverage["untested_session_count"] == 6
    assert coverage["tested_session_fraction"] == 0.4
    assert coverage["first_test_session"] == "2026-10-16"
    assert coverage["last_test_session"] == "2026-10-22"
    assert coverage["untested_session_dates"] == [
        "2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15",
        "2026-10-20", "2026-10-23",
    ]


def test_runner_coverage_never_conflates_input_span_with_test_span(tmp_path):
    filename = make_csv(tmp_path, sessions=7)
    report = run(
        filename,
        expected_session_span=(date(2026, 10, 12), date(2026, 10, 20)),
    )
    assert len(report["folds"]) == 1
    assert report["last_session"] == "2026-10-20"
    assert report["evaluation_coverage"]["last_test_session"] == "2026-10-19"
    assert "2026-10-20" in report["evaluation_coverage"]["untested_session_dates"]


def test_adverse_slippage_stress_reruns_same_folds_without_changing_baseline(
    tmp_path, monkeypatch,
):
    import backtesting.run_walk_forward as runner_module

    filename = make_csv(tmp_path)
    original_evaluator = runner_module.evaluate_fixed_baseline_folds
    seen_slippage = []

    def track_evaluation(folds, **kwargs):
        seen_slippage.append(kwargs["slippage_pct"])
        return original_evaluator(folds, **kwargs)

    monkeypatch.setattr(
        runner_module, "evaluate_fixed_baseline_folds", track_evaluation
    )
    baseline = run(filename)
    seen_slippage.clear()
    report = run(filename, stress_slippage_pcts=(0.002, 0.005))
    assert seen_slippage == [0.001, 0.002, 0.005]
    assert report["folds"] == baseline["folds"]
    assert report["summary"] == baseline["summary"]
    assert report["evaluation_coverage"] == baseline["evaluation_coverage"]
    assert report["source_sha256"] == baseline["source_sha256"]
    assert [item["slippage_pct"] for item in report["slippage_stress"]] == [
        0.002, 0.005,
    ]
    assert all(item["folds"][0]["first_test_date"] == "2026-10-16"
               for item in report["slippage_stress"])
    assert all("total_return_pct" not in item["summary"]
               for item in report["slippage_stress"])
    assert json.loads(json.dumps(report)) == report
    assert baseline["slippage_stress"] == []


@pytest.mark.parametrize("bad_stresses", [
    [0.002], "0.002", None, (0.002, 0.002), (0.003, 0.002),
    (0.001,), (0.0005,), (float("nan"),), (float("inf"),),
    (True,), ("0.002",), (1,), (0.002, 0.003, 0.004, 0.005, 0.006, 0.007),
])
def test_runner_rejects_invalid_stress_scenarios(tmp_path, bad_stresses):
    with pytest.raises(ValueError, match="Stress slippage"):
        run(make_csv(tmp_path), stress_slippage_pcts=bad_stresses)


@pytest.mark.parametrize("bad_baseline", [float("nan"), float("inf"), True, -0.1, 1])
def test_runner_rejects_invalid_baseline_slippage(tmp_path, bad_baseline):
    with pytest.raises(ValueError, match="baseline slippage"):
        run(make_csv(tmp_path), slippage_pct=bad_baseline)


def test_cli_emits_adverse_slippage_stress_scenarios(tmp_path, capsys):
    filename = make_csv(tmp_path)
    main([
        "--csv", str(filename), "--symbol", "SPY",
        "--first-session", "2026-10-12",
        "--last-session", "2026-10-19",
        "--closed-sessions", "none",
        "--train-sessions", "3", "--test-sessions", "2",
        "--stress-slippage-pcts", "0.002,0.005",
    ])
    report = json.loads(capsys.readouterr().out)
    assert [item["slippage_pct"] for item in report["slippage_stress"]] == [
        0.002, 0.005,
    ]


@pytest.mark.parametrize("bad", ["", "0.002,", "oops", "0.001", "0.005,0.002", "nan"])
def test_cli_rejects_invalid_stress_scenarios(tmp_path, bad):
    filename = make_csv(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main([
            "--csv", str(filename), "--symbol", "SPY",
            "--first-session", "2026-10-12",
            "--last-session", "2026-10-19",
            "--closed-sessions", "none",
            "--train-sessions", "3", "--test-sessions", "2",
            "--stress-slippage-pcts", bad,
        ])
    assert exc.value.code == 2
