#!/usr/bin/env bash
set -euo pipefail

cd /home/discord-bot
git pull --ff-only
mkdir -p logs

uv sync --locked --no-dev --group indexer

exec uv run --frozen --no-dev --group indexer python main.py
