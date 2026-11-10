#!/usr/bin/env bash
# Morning routine entry point: grades yesterday, builds today's digest, logs top plays, saves text + json.
cd "$(dirname "$0")"
D=$(TZ=America/New_York date +%F)
python3 bet.py digest "$@" | tee "digests/$D.txt"
python3 bet.py --json track report > "digests/$D.report.json"
python3 -c "from betlib import net; net.purge()" >/dev/null 2>&1
