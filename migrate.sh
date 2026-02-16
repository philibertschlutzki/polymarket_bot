#!/bin/bash
# Housekeeping Script to structure the repo for Nautilus Trader V2

# 1. Create Directories
mkdir -p legacy_v1
mkdir -p nautilus_v2/config
mkdir -p nautilus_v2/strategies
mkdir -p nautilus_v2/data
mkdir -p .github/workflows

# 2. Move Legacy Files
# Move everything except the new folders, git, and this script to legacy_v1
for item in * .[^.]*; do
    case "$item" in
        "legacy_v1"|"nautilus_v2"|".git"|".github"|"migrate.sh"|"requirements.txt"|"ARCHITECTURE.md"|"."|"..")
            continue
            ;;
        *)
            if [ -e "$item" ]; then
                mv "$item" legacy_v1/
            fi
            ;;
    esac
done

# 3. Create Init Files
touch nautilus_v2/__init__.py
touch nautilus_v2/strategies/__init__.py

# 4. Create .gitignore
cat <<EOT > .gitignore
__pycache__/
*.py[cod]
.venv/
venv/
.env
.env.prod
nautilus_v2/config/secrets.toml
nautilus_v2/data/
*.catalog
*.parquet
.vscode/
.idea/
legacy_v1/
EOT

# 5. Create .env example
cat <<EOT > .env.example
GOOGLE_API_KEY="your_gemini_key"
POLYGON_PRIVATE_KEY="your_wallet_private_key"
POLYGON_ADDRESS="your_wallet_address"
POLYGON_RPC_URL="https://polygon-rpc.com"
LOG_LEVEL="INFO"
EOT

echo "Migration structure created."
