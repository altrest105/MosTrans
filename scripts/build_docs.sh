#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "[docs] .venv не найден. Создайте окружение и установите корневой requirements.txt." >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q -r docs/requirements.txt

rm -rf docs/_build
mkdir -p docs/_build

python -m sphinx -W --keep-going -b html docs docs/_build/html

echo "[docs] Sphinx: $ROOT/docs/_build/html/index.html"
echo "[docs] Для локального просмотра:"
echo "       python -m http.server 8088 --directory docs/_build/html"
