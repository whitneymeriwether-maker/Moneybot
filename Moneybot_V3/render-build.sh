#!/usr/bin/env bash
# V3 staging only. Configure the V3 Render service build command as:
# bash Moneybot_V3/render-build.sh
# Do not change the V2/main Render service.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pip install --disable-pip-version-check -r Moneybot_V3/requirements.txt
python -m pip install --disable-pip-version-check pytest==8.4.2
python -m compileall -q Moneybot_V3
PYTHONPATH=Moneybot_V3 python -m pytest -q Moneybot_V3/test_staging_http_smoke.py Moneybot_V3/tests/test_paper_status_server.py
python - <<'PY'
import psycopg
assert psycopg.__version__.split(".")[0] == "3"
from pathlib import Path
import sys
sys.path.insert(0, str(Path("Moneybot_V3").resolve()))
import paper_status_server as server
assert server._STATUS["trading_state"] == "NOT_ACTIVATED"
assert server._STATUS["automatic_paper_trading"] is False
assert server._STATUS["real_money_trading"] is False
assert server._STATUS["market_data"] == "NOT_CONNECTED"
assert server._STATUS["execution_time_risk_gate"] == "NOT_CONNECTED"
print("V3 staging dependencies, server import, and disabled execution verified")
PY
