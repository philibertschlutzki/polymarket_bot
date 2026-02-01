#!/bin/bash
set -e  # Exit on error

echo "🚀 Polymarket Bot - Raspberry Pi Deployment"
echo "============================================"

# Ensure we are in the project root (parent of scripts/)
cd "$(dirname "$0")/.."
WORKING_DIR=$(pwd)
echo "📂 Working Directory: $WORKING_DIR"

# 1. System Requirements Check
echo "📋 Checking system requirements..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found. Installing..."
    sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
fi

if ! command -v git &> /dev/null; then
    echo "❌ Git not found. Installing..."
    sudo apt-get install -y git
fi

# 2. Virtual Environment Setup
echo "🐍 Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 3. Dependencies Installation
echo "📦 Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Interactive GitHub PAT Configuration
echo ""
echo "🔑 GitHub Authentication Setup"
echo "------------------------------"

if [ ! -f .env ]; then
    cp .env.example .env
    echo "ℹ️  Created .env file (hidden)"
fi

# Check if PAT already exists in .env
if grep -q "^GITHUB_PAT=" .env && [ -n "$(grep "^GITHUB_PAT=" .env | cut -d '=' -f2)" ]; then
    echo "✅ GitHub PAT already configured in .env"
else
    echo "Please create a GitHub Personal Access Token:"
    echo "1. Go to: https://github.com/settings/tokens/new"
    echo "2. Select scope: 'repo' (Full control of private repositories)"
    echo "3. Generate token and paste below"
    echo ""
    read -sp "Enter your GitHub PAT: " GITHUB_PAT
    echo ""

    # Validate PAT by testing GitHub API
    echo "🔍 Validating PAT..."
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: token $GITHUB_PAT" \
        https://api.github.com/user)

    if [ "$HTTP_CODE" -eq 200 ]; then
        echo "✅ PAT is valid!"
        echo "GITHUB_PAT=$GITHUB_PAT" >> .env
    else
        echo "❌ Invalid PAT (HTTP $HTTP_CODE). Please check your token."
        exit 1
    fi
fi

# 5. Gemini API Key Configuration
echo ""
echo "🔑 Gemini API Configuration"
echo "----------------------------"

GEMINI_KEY_VAL=$(grep "^GEMINI_API_KEY=" .env | cut -d '=' -f2)
if grep -q "^GEMINI_API_KEY=" .env && [ -n "$GEMINI_KEY_VAL" ] && [ "$GEMINI_KEY_VAL" != "your_gemini_api_key_here" ]; then
    echo "✅ Gemini API Key already configured in .env"
else
    echo "Please create a Gemini API Key:"
    echo "1. Go to: https://aistudio.google.com/app/apikey"
    echo "2. Create a new API key"
    echo "3. Paste it below"
    echo ""
    read -sp "Enter your Gemini API Key: " GEMINI_API_KEY
    echo ""

    # Basic validation (non-empty, reasonable length)
    if [ -z "$GEMINI_API_KEY" ] || [ ${#GEMINI_API_KEY} -lt 20 ]; then
        echo "❌ Invalid API key. Please check and try again."
        exit 1
    fi

    if grep -q "^GEMINI_API_KEY=your_gemini_api_key_here" .env; then
         sed -i "s|^GEMINI_API_KEY=.*|GEMINI_API_KEY=$GEMINI_API_KEY|" .env
    else
         echo "GEMINI_API_KEY=$GEMINI_API_KEY" >> .env
    fi
    echo "✅ Gemini API Key configured!"
fi

# 6. Git Remote Configuration
echo ""
echo "🔧 Configuring Git remote with PAT..."
GITHUB_PAT=$(grep "^GITHUB_PAT=" .env | cut -d '=' -f2)
REPO_URL=$(git config --get remote.origin.url)

# Extract owner/repo from current URL
if [[ $REPO_URL =~ github\.com[:/]([^/]+)/([^/.]+) ]]; then
    OWNER="${BASH_REMATCH[1]}"
    REPO="${BASH_REMATCH[2]}"

    # Set new URL with PAT
    NEW_URL="https://${GITHUB_PAT}@github.com/${OWNER}/${REPO}.git"
    git remote set-url origin "$NEW_URL"
    echo "✅ Git remote configured with authentication"
else
    echo "⚠️  Could not parse GitHub URL: $REPO_URL"
fi

# 7. Database Initialization
echo ""
echo "🗄️  Initializing database..."

# Load env vars to check DATABASE_URL
set -a
source .env
set +a

if [ -z "$DATABASE_URL" ] || [[ "$DATABASE_URL" == "sqlite"* ]]; then
    echo "ℹ️  Using SQLite (Default). Creating database directory..."
    mkdir -p database
    # Fix permissions if needed
    sudo chown -R $(whoami):$(whoami) database
    chmod -R u+rw database
fi

# Set PYTHONPATH to include current dir so imports work
export PYTHONPATH=$WORKING_DIR
python3 -c "from src import database; database.init_database()"
echo "✅ Database initialized with 1000 USDC starting capital"

# 8. .gitignore Configuration
echo ""
echo "📝 Updating .gitignore..."
if ! grep -q "*.db" .gitignore 2>/dev/null; then
    echo "*.db" >> .gitignore
fi
if ! grep -q "logs/" .gitignore 2>/dev/null; then
    echo "logs/" >> .gitignore
fi

# 9. Log Directory Setup
mkdir -p logs
# Fix permissions for logs directory AND all existing files
sudo chown -R $(whoami):$(whoami) logs
chmod -R u+rw logs
# Remove any existing log files that might have wrong permissions
rm -f logs/bot.log logs/bot.error.log logs/bot.log.*

# 10. Logrotate Configuration
echo ""
echo "🔄 Configuring Logrotate..."
LOGROTATE_CONF="/etc/logrotate.d/polymarket-bot"
USER=$(whoami)

# We use sudo to write to /etc/logrotate.d/
if sudo bash -c "cat > $LOGROTATE_CONF" <<EOF
$WORKING_DIR/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 $USER $USER
}
EOF
then
    echo "✅ Logrotate configured."
else
    echo "⚠️  Failed to configure logrotate (sudo required)."
fi

# 11. systemd Service Installation
echo ""
echo "⚙️  Installing systemd service..."

SERVICE_FILE="/etc/systemd/system/polymarket-bot.service"

sudo tee $SERVICE_FILE > /dev/null <<EOF
[Unit]
Description=Polymarket AI Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$WORKING_DIR
Environment="PATH=$WORKING_DIR/venv/bin:/usr/bin"
# ExecStart points to src/main.py
ExecStartPre=/bin/bash -c 'mkdir -p $WORKING_DIR/logs && chown -R $USER:$USER $WORKING_DIR/logs && chmod -R u+rw $WORKING_DIR/logs'
ExecStart=$WORKING_DIR/venv/bin/python3 $WORKING_DIR/src/main.py
Restart=on-failure
RestartSec=10
StartLimitBurst=5
StartLimitIntervalSec=600

# Logging - systemd redirects stderr only, application handles its own log files
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "✅ Service file created at $SERVICE_FILE"

# 12. Enable and Start Service
echo ""
read -p "Start the bot service now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo systemctl daemon-reload
    sudo systemctl enable polymarket-bot.service
    sudo systemctl start polymarket-bot.service

    echo ""
    echo "✅ Bot is now running!"
    echo ""
    echo "Useful commands:"
    echo "  - Check status: sudo systemctl status polymarket-bot"
    echo "  - View logs:    tail -f logs/bot.log"
    echo "  - Stop bot:     sudo systemctl stop polymarket-bot"
    echo "  - Restart bot:  sudo systemctl restart polymarket-bot"
fi

echo ""
echo "🎉 Deployment complete!"
echo "ℹ️  Note: Configuration is stored in .env (hidden file). Use 'ls -a' to view."
