#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

DB_PATH="database/polymarket.db"

echo "==> Upload lokale Datenbank zu GitHub..."

# Wechsle ins Repository-Root
cd "$(git rev-parse --show-toplevel)"

# Prüfe ob Datei existiert
if [ ! -f "${DB_PATH}" ]; then
    echo -e "${RED}Fehler: ${DB_PATH} nicht gefunden${NC}"
    exit 1
fi

# Zeige Dateigröße
DB_SIZE=$(du -h "${DB_PATH}" | cut -f1)
echo "Dateigröße: ${DB_SIZE}"

# Sichere aktuellen Branch
CURRENT_BRANCH=$(git branch --show-current)

# Hole Remote-Status
echo "==> Hole Remote-Status..."
git fetch origin

# Reset zu Remote (verwirft lokale Commits, behält Dateien)
echo "==> Synchronisiere mit Remote..."
git reset --soft origin/${CURRENT_BRANCH}

# Leere Staging Area
git reset HEAD

# Füge NUR die Datenbank hinzu
echo "==> Füge Datenbank hinzu..."
git add -f "${DB_PATH}"

# Prüfe ob es Änderungen gibt
if git diff --cached --quiet; then
    echo -e "${YELLOW}Keine Änderungen - Datenbank ist bereits aktuell${NC}"
    exit 0
fi

# Committe
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
echo "==> Erstelle Commit..."
git commit -m "Update database: ${TIMESTAMP}"

# Push
echo "==> Pushe zu GitHub..."
git push origin ${CURRENT_BRANCH}

echo -e "${GREEN}✓ Datenbank erfolgreich hochgeladen!${NC}"
echo "Commit: $(git log -1 --oneline)"
