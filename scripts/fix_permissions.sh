#!/bin/bash
echo "🔧 Fixing permissions for Polymarket Bot..."

# Ensure we are in the project root (parent of scripts/)
cd "$(dirname "$0")/.."
WORKING_DIR=$(pwd)
echo "📂 Working Directory: $WORKING_DIR"

# Stop service
sudo systemctl stop polymarket-bot.service 2>/dev/null || true

# Fix logs directory
if [ -d logs ]; then
    sudo chown -R $(whoami):$(whoami) logs/
    chmod -R u+rw logs/
    rm -f logs/*.log logs/*.log.*
fi

# Fix database
if [ -f database/polymarket.db ]; then
    sudo chown $(whoami):$(whoami) database/polymarket.db
    chmod u+rw database/polymarket.db
fi
# Also directory
if [ -d database ]; then
    sudo chown -R $(whoami):$(whoami) database/
    chmod -R u+rw database/
fi

# Fix .env
if [ -f .env ]; then
    sudo chown $(whoami):$(whoami) .env
    chmod 600 .env
fi

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl start polymarket-bot.service

echo "✅ Permissions fixed! Check status with:"
echo "   sudo systemctl status polymarket-bot"
