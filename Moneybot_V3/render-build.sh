#!/usr/bin/env bash
# V3 staging only. Configure the V3 Render service build command as:
# bash Moneybot_V3/render-build.sh
# Do not change the V2/main Render service.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pip install --disable-pip-version-check -r Moneybot_V3/requirements.txt
python -m compileall -q Moneybot_V3
python - <<'PY'
import psycopg
assert psycopg.__version__.split(".")[0] == "3"
from pathlib import Path
assert Path("Moneybot_V3/paper_status_server.py").is_file()
print("V3 staging build prerequisites verified")
PY
