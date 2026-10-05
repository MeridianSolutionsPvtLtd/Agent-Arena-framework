#!/bin/bash
set -euo pipefail

APP_DIR=/home/site/wwwroot
cd "$APP_DIR"

# Self-contained bootstrap: works whether or not Oryx built a virtualenv.
# Kept outside wwwroot so a `clean: true` deploy does not wipe it; /home is
# persistent storage, so the venv survives restarts and is only rebuilt when
# requirements.txt changes.
VENV=/home/venv/agent-combine
STAMP="$VENV/.requirements.sha256"

# A venv copied from another machine leaves bin/python as a dangling symlink
# that still passes the executable-bit test, so probe by running it.
python_works() {
  [[ -n "${1:-}" ]] && "$1" -c "import sys" >/dev/null 2>&1
}

has_deps() {
  [[ -n "${1:-}" ]] && "$1" -c "import fitz, gunicorn, fastapi" >/dev/null 2>&1
}

# Prefer an Oryx-built venv that already has everything installed.
for candidate in /antenv/bin/python "$APP_DIR/antenv/bin/python"; do
  if python_works "$candidate" && has_deps "$candidate"; then
    echo "Using Oryx virtualenv: $candidate"
    exec "$candidate" -m gunicorn \
      --bind=0.0.0.0:${PORT:-8000} \
      --timeout 600 \
      -k uvicorn.workers.UvicornWorker \
      main:app
  fi
done

echo "No usable Oryx virtualenv; bootstrapping $VENV"
unset PYTHONPATH

BASE_PYTHON=""
for candidate in /opt/python/3.12.13/bin/python3 "$(command -v python3 || true)"; do
  if python_works "$candidate"; then
    BASE_PYTHON="$candidate"
    break
  fi
done

if [[ -z "$BASE_PYTHON" ]]; then
  echo "ERROR: no working Python interpreter on this host."
  exit 1
fi
echo "Base Python: $BASE_PYTHON ($("$BASE_PYTHON" --version 2>&1))"

WANT_HASH="$(sha256sum requirements.txt | cut -d' ' -f1)"
HAVE_HASH="$(cat "$STAMP" 2>/dev/null || true)"

if ! python_works "$VENV/bin/python"; then
  echo "Creating virtualenv (copies mode so it stays valid across restarts)..."
  rm -rf "$VENV"
  mkdir -p "$(dirname "$VENV")"
  "$BASE_PYTHON" -m venv --copies "$VENV"
  HAVE_HASH=""
fi

if [[ "$WANT_HASH" != "$HAVE_HASH" ]] || ! has_deps "$VENV/bin/python"; then
  echo "Installing requirements.txt (this only runs when dependencies change)..."
  "$VENV/bin/python" -m pip install --upgrade pip setuptools wheel
  "$VENV/bin/python" -m pip install --no-cache-dir -r requirements.txt
  echo "$WANT_HASH" > "$STAMP"
else
  echo "Dependencies already up to date; skipping install."
fi

"$VENV/bin/python" -c "import fitz; print('pymupdf OK', fitz.__doc__)"

exec "$VENV/bin/python" -m gunicorn \
  --bind=0.0.0.0:${PORT:-8000} \
  --timeout 600 \
  -k uvicorn.workers.UvicornWorker \
  main:app
