# Polymarket AI Autonomous Trading Bot 🤖📈

Ein vollautomatisches, KI-gestütztes System, das 24/7 Polymarket-Märkte analysiert, Value-Bets identifiziert und die Performance in einem Live-Dashboard trackt.

Konzipiert für den Betrieb auf einem **Raspberry Pi** oder Linux-Server.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi%20%7C%20Linux-green)
![Status](https://img.shields.io/badge/Status-Production-brightgreen)

---

## 🚀 Features (v2.0)

### 🧠 Intelligente Analyse
*   **Gemini 2.0 Flash Integration:** Nutzt Google Search Grounding für Echtzeit-Faktenanalyse.
*   **Edge-Erkennung:** Berechnet Wahrscheinlichkeiten und vergleicht diese mit Marktpreisen.
*   **Kelly-Kriterium:** Dynamisches Risikomanagement zur Berechnung der optimalen Positionsgröße (max. 50% Portfolio-Cap).

### ⚙️ Autonomie & Persistenz
*   **SQLite Datenbank:** Speichert Portfolio-Status (`portfolio_state`), aktive Wetten (`active_bets`) und Resultate (`results`) lokal und sicher.
*   **Auto-Settlement:** Überwacht Wetten via GraphQL API und verbucht Gewinne/Verluste automatisch nach Marktschluss.
*   **Quota-Management:** Intelligenter 15-Minuten-Zyklus zur Einhaltung der kostenlosen Gemini API-Limits (95% Auslastung).
*   **Systemd Service:** Selbstheilender Prozess mit Auto-Restart bei Fehlern.

### 📊 Reporting
*   **Live-Dashboard:** Generiert automatisch ein `PERFORMANCE_DASHBOARD.md` mit ASCII-Charts, Win-Rate, Sharpe-Ratio und ROI.
*   **Git Auto-Push:** Pusht Dashboard-Updates automatisch zurück in dieses Repository (via PAT).

---

## 🛠 Voraussetzungen

*   **Hardware:** Raspberry Pi (3B+ oder neuer empfohlen) oder Linux VM.
*   **Software:** Python 3.10+, Git.
*   **Accounts:**
    *   GitHub Account (für Auto-Push)
    *   Google AI Studio API Key (kostenlos)
    *   *(Optional)* Polymarket Account (aktuell Paper-Trading Modus)

---

## 📦 Installation & Deployment

Das System verfügt über ein automatisiertes Deployment-Script für Raspberry Pi / Debian-basierte Systeme.
### Oneliner
```bash
git clone https://github.com/philibertschlutzki/polymarket_bot.git && cd polymarket_bot && chmod +x deploy_raspberry_pi.sh && ./deploy_raspberry_pi.sh && chmod +x setup_logrotate.sh && ./setup_logrotate.sh
```
### 1. Repository klonen
```bash
git clone https://github.com/philibertschlutzki/polymarket_bot.git
cd polymarket_bot
```

### 2. Deployment starten
Das Script installiert Abhängigkeiten, richtet die Datenbank ein, konfiguriert den Systemdienst und hilft beim Erstellen der `.env` Datei.

```bash
chmod +x deploy_raspberry_pi.sh
./deploy_raspberry_pi.sh
```

**Während der Installation wirst du aufgefordert:**
1.  Einen **GitHub Personal Access Token (PAT)** einzugeben (Scope: `repo`).
2.  Deinen **Google Gemini API Key** zu bestätigen.

### 3. Log-Rotation (Optional)
Damit die Logfiles den Speicher nicht füllen:
```bash
chmod +x setup_logrotate.sh
./setup_logrotate.sh
```

---

## 🖥️ Monitoring & Steuerung

Da der Bot als Hintergrunddienst läuft, nutzen Sie folgende Befehle zur Steuerung:

**Status prüfen:**
```bash
sudo systemctl status polymarket-bot
```

**Live-Logs ansehen:**
```bash
tail -f logs/bot.log
```

**Bot stoppen/starten:**
```bash
sudo systemctl stop polymarket-bot
sudo systemctl start polymarket-bot
```

---

## 📂 Projektstruktur

```
polymarket_bot/
├── main.py                 # Hauptlogik (Scheduler, API-Calls)
├── database.py             # SQLite Datenbank-Layer
├── dashboard.py            # Generierung des Markdown-Dashboards
├── git_integration.py      # Auto-Push Logik
├── deploy_raspberry_pi.sh  # Setup-Script
├── requirements.txt        # Python Abhängigkeiten
├── polymarket.db           # Datenbank (lokal, nicht in Git)
├── logs/                   # Logfiles (rotiert)
└── PERFORMANCE_DASHBOARD.md # Automatisch aktualisierter Report
```

---

## ⚙️ Konfiguration (.env)

Die Konfiguration erfolgt über die `.env` Datei. Das Deployment-Script erstellt diese automatisch, aber hier sind die Details:

```env
# Credentials
GEMINI_API_KEY=Dein_Google_Key
GITHUB_PAT=Dein_Github_Token

# Trading Strategie
MIN_VOLUME=10000          # Min. Volumen für Analyse ($)
MIN_PRICE=0.05            # Min. Preis (5 Cent)
MAX_PRICE=0.95            # Max. Preis (95 Cent)
HIGH_VOLUME_THRESHOLD=50000 # Ausnahme für hohe Liquidität

# System
FETCH_MARKET_LIMIT=100    # Anzahl Märkte pro API-Call
TOP_MARKETS_TO_ANALYZE=15 # Max. KI-Analysen pro 15min (Quota-Schutz)
```

---

## 📈 Dashboard

Das Dashboard [PERFORMANCE_DASHBOARD.md](./PERFORMANCE_DASHBOARD.md) wird automatisch aktualisiert, wenn:
1.  Eine neue Wette platziert wurde.
2.  Eine Wette abgeschlossen (resolved) wurde.

Es enthält keine Live-Preise, sondern den Snapshot zum Zeitpunkt der Generierung.

---

## ⚠️ Disclaimer

Dieses Tool dient ausschließlich zu Bildungs- und Forschungszwecken. 
*   Die "Wetten" sind aktuell fiktiv (Paper Trading) und werden gegen ein virtuelles Portfolio in der SQLite-Datenbank verrechnet.
*   Es erfolgt keine Interaktion mit Smart Contracts oder echten Funds auf der Polygon Blockchain.
*   Nutzung auf eigene Gefahr.
