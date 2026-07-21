#!/usr/bin/env bash
set -euo pipefail

cd /home/discord-bot
git pull --ff-only
mkdir -p logs

uv sync --locked --no-dev --group embeddings

exec uv run --frozen --no-dev --group embeddings python main.py
