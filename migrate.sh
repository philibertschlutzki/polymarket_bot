#!/bin/bash

# Farben für Output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}>>> Starte Migration zu Nautilus Trader Struktur...${NC}"

# 1. Verzeichnisse erstellen
echo -e "${GREEN}1. Erstelle Ordnerstruktur...${NC}"
mkdir -p legacy_v1
mkdir -p nautilus_v2/config
mkdir -p nautilus_v2/strategies
mkdir -p nautilus_v2/data
mkdir -p .github/workflows

# 2. Alte Dateien verschieben (Housekeeping)
# Wir verschieben alles außer .git, die neuen Ordner und dieses Skript selbst
echo -e "${GREEN}2. Verschiebe alten Code nach legacy_v1/...${NC}"

# Loop durch alle Dateien im aktuellen Verzeichnis
for item in * .[^.]*; do
    # Überspringe spezielle Verzeichnisse und Dateien
    case "$item" in
        "legacy_v1"|"nautilus_v2"|".git"|".github"|"migrate.sh"|"requirements.txt"|"."|"..")
            continue
            ;;
        *)
            # Prüfen ob Datei existiert (verhindert Fehler bei leerem Match)
            if [ -e "$item" ]; then
                echo "   Verschiebe: $item"
                mv "$item" legacy_v1/
            fi
            ;;
    esac
done

# 3. Dummy-Dateien und Configs erstellen
echo -e "${GREEN}3. Erstelle Boilerplate-Dateien...${NC}"

# Leere __init__.py Dateien damit Python die Ordner als Pakete erkennt
touch nautilus_v2/__init__.py
touch nautilus_v2/strategies/__init__.py

# .env.example Vorlage erstellen
cat <<EOT >> .env.example
# --- Google Gemini AI ---
GOOGLE_API_KEY="dein_gemini_api_key_hier"

# --- Polymarket / Polygon ---
POLYGON_PRIVATE_KEY="dein_wallet_private_key"
POLYGON_ADDRESS="deine_wallet_adresse"
# Optional: RPC Node (falls Standard Node zu langsam ist)
POLYGON_RPC_URL="https://polygon-rpc.com"

# --- Nautilus Config ---
LOG_LEVEL="INFO"
EOT

# .gitignore erstellen (falls noch nicht existent oder unvollständig)
cat <<EOT >> .gitignore
# Python
__pycache__/
*.py[cod]
.venv/
venv/

# Environment / Secrets (WICHTIG!)
.env
.env.prod
nautilus_v2/config/secrets.toml

# Nautilus Data
nautilus_v2/data/
*.catalog
*.parquet

# IDE
.vscode/
.idea/
EOT

# README Update Hinweis
echo "# Nautilus Polymarket Bot V2" > README.md
echo "Migration from legacy bot completed on $(date)." >> README.md

echo -e "${YELLOW}>>> Migration abgeschlossen!${NC}"
echo -e "Dein alter Code liegt jetzt in: ${GREEN}legacy_v1/${NC}"
echo -e "Dein neues Projekt liegt in:    ${GREEN}nautilus_v2/${NC}"
echo -e "Führe jetzt 'uv pip install -r requirements.txt' aus."