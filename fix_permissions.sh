#!/bin/bash
echo "🔧 Fixing permissions for Polymarket Bot..."

# Stop service
sudo systemctl stop polymarket-bot.service 2>/dev/null || true

# Fix logs directory
if [ -d logs ]; then
    sudo chown -R $(whoami):$(whoami) logs/
    chmod -R u+rw logs/
    rm -f logs/*.log logs/*.log.*
fi

# Fix database
if [ -f polymarket.db ]; then
    sudo chown $(whoami):$(whoami) polymarket.db
    chmod u+rw polymarket.db
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
