#!/usr/bin/env bash
# Start DesignVault — design inspiration curation tool
set -euo pipefail
cd "$(dirname "$0")"

# Find uv
UV="$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")"
if [ ! -x "$UV" ]; then
  echo "Error: uv not found. Install with: brew install uv"
  exit 1
fi

# Ensure Playwright's Chromium is installed (idempotent, fast if already present)
echo "Checking browser install..."
"$UV" run --with playwright playwright install chromium 2>/dev/null \
  || echo "Note: run 'playwright install chromium' if URL capture fails"

echo "Starting DesignVault..."
"$UV" run --with flask --with pillow --with playwright app.py
