#!/usr/bin/env bash
# bolt installer (Mac). Run:
#   curl -fsSL https://raw.githubusercontent.com/boltmotivation-coder/bolt-ingest/main/install.sh | bash
set -e

REPO="boltmotivation-coder/bolt-ingest"

echo "== Installing bolt =="

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. macOS will prompt you to install developer tools; accept it, then re-run this command."
  xcode-select --install || true
  exit 1
fi

python3 -m pip install --user -q pipx 2>/dev/null || python3 -m pip install --user -q --break-system-packages pipx
python3 -m pipx ensurepath >/dev/null 2>&1 || true
export PATH="$HOME/.local/bin:$PATH"

python3 -m pipx install --force "git+https://github.com/$REPO.git"

echo ""
echo "Done. Close this terminal, open a new one, and type: bolt"
