#!/bin/bash

LOGROTATE_CONF="/etc/logrotate.d/polymarket-bot"
WORKING_DIR=$(pwd)

sudo tee $LOGROTATE_CONF > /dev/null <<EOF
$WORKING_DIR/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 $(whoami) $(whoami)
}
EOF

echo "✅ Log rotation configured (7-day retention)"
