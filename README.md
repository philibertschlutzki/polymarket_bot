---

# 🧠 Polymarket AI Trader (Nautilus & Gemini V2)

Ein professioneller, Event-Driven Trading-Bot für **Polymarket** (Polygon Blockchain).
Dieses System nutzt das **Nautilus Trader Framework** für robustes Order-Management und **Google Gemini 2.0** (mit Search Grounding) für fundamentale Sentiment-Analyse von Echtzeit-Nachrichten.

---

## ✨ Hauptfunktionen

Das System ist modular aufgebaut und bietet folgende Kernfeatures:

* **🔍 Intelligenter Markt-Scanner:**
* Durchsucht die Polymarket Gamma API automatisch nach handelbaren Märkten.
* **Filterkriterien:** Minimales tägliches Volumen, maximaler Spread und Zeit bis zum Ablauf (konfigurierbar).
* Filtert illiquide oder uninteressante Märkte automatisch aus.


* **🤖 KI-gestützte Analyse (Gemini 2.0):**
* Nutzt **Google Gemini 2.0 Flash** für die Entscheidungsfindung.
* **Search Grounding:** Die KI führt live Google-Suchen durch, um aktuelle News zum Event zu finden (keine Halluzinationen bei neuen Ereignissen).
* **Structured Output:** Die KI liefert Entscheidungen im strikten JSON-Format (`buy`, `sell`, `hold`, `confidence`, `reasoning`).


* **⚡ Nautilus Trading Engine:**
* Verwendet den offiziellen Polymarket-Adapter für zuverlässige Execution.
* **Smart Orders:** Platziert Limit-Orders am Ask-Preis (plus Slippage-Toleranz), um Taker-Gebühren zu minimieren und Ausführung zu garantieren.
* **Risiko-Management:** Konfigurierbare maximale Positionsgröße (in USDC) und Slippage-Schutz.


* **📱 Echtzeit-Benachrichtigungen:**
* Asynchrone Telegram-Integration.
* Sendet Updates zu Scanner-Funden, KI-Analysen und ausgeführten Trades (Entry/Exit).


* **🐳 Container-First:**
* Vollständige Docker & Docker Compose Unterstützung inkl. Redis für Caching.



---

## 🏗 Architektur

Das System folgt einer klaren Trennung der Verantwortlichkeiten:

1. **Initialization (`src/main.py`):** Lädt Konfiguration, initialisiert die Nautilus Node und startet den Scanner.
2. **Scanning (`src/scanner/`):** Identifiziert Märkte basierend auf Liquidität und Spread via Gamma API und registriert sie als Instrumente im System.
3. **Strategy Loop (`src/strategies/`):**
* Abonniert Live-Daten für registrierte Märkte.
* Führt periodische Analysen durch (z.B. alle 24h).


4. **Intelligence Layer (`src/intelligence/`):**
* Erhält Kontext (Frage, Preise, Outcomes).
* Fragt Gemini mit Web-Search-Tools ab.
* Mapped die KI-Antwort (z.B. "Trump") auf das korrekte `InstrumentID` mittels Fuzzy-Matching.


5. **Execution:** Sendet signierte Transaktionen an die Polygon Blockchain via Nautilus Adapter.

---

## 🚀 Installation & Setup

### Voraussetzungen

* **Python 3.11** oder **Docker**
* **Google Cloud API Key** (für Gemini)
* **Polygon Wallet** (Private Key & Address) mit POL (Gas) und USDC.e (Collateral).
* **Polymarket API Credentials** (API Key, Secret, Passphrase).
* **Telegram Bot Token** (optional).

### Option A: Docker (Empfohlen)

1. **Repository klonen:**
```bash
git clone https://github.com/philibertschlutzki/polymarket_bot.git
cd polymarket_bot

```


2. **Umgebungsvariablen setzen:**
Erstelle eine `.env` Datei basierend auf der Vorlage:
```bash
cp .env.example .env
nano .env

```


*Fülle alle erforderlichen Keys aus.*
3. **Starten:**
Startet Redis und den Bot-Container.
```bash
docker-compose up -d --build

```



### Option B: Lokale Installation

1. **Dependencies installieren:**
```bash
pip install -r requirements.txt

```


2. **Konfiguration prüfen:**
Passe bei Bedarf `config/config.toml` an.
3. **Bot starten:**
```bash
export PYTHONPATH=$PYTHONPATH:.
python src/main.py

```


### Paper Trading Mode (Simulation)

Der Bot unterstützt einen Paper Trading Modus, der Live-Daten von Polymarket nutzt, aber die Order-Ausführung simuliert (kein echtes Geld/Gas).

Um Paper Trading zu aktivieren:
1. Setze `mode = "paper"` in `config/config.toml` (Standard).
2. Starte den Bot wie gewohnt.

### Lokale Docker Simulation

Um das Deployment lokal exakt wie auf dem Server zu simulieren:

1. Stelle sicher, dass `.env` konfiguriert ist.
2. Führe das Simulations-Skript aus:
   ```bash
   ./simulate_deploy.sh
   ```
Dies baut den Docker-Container und startet den Bot im konfigurierten Modus.


---

## ⚙️ Konfiguration

Die Steuerung erfolgt über zwei Dateien:

### 1. Secrets (`.env`)

Hier liegen sensible Daten. Siehe `.env.example` für Details.

* `GOOGLE_API_KEY`: Zugriff auf Gemini.
* `POLYGON_PRIVATE_KEY`: Signieren von Transaktionen.
* `POLYMARKET_API_*`: Authentifizierung bei Polymarket.

### 2. Parameter (`config/config.toml`)

Hier wird das Verhalten des Bots gesteuert:

```toml
[risk]
max_position_size_usdc = 50.0  # Max Invest pro Trade
slippage_tolerance_ticks = 2   # Erlaubter Preisrutsch

[scanner]
min_daily_volume = 1000.0      # Nur liquide Märkte
max_spread = 0.05              # Max 5 Cent Spread
days_to_expiration = 7         # Zeithorizont

[gemini]
model = "gemini-2.0-flash-exp"
temperature = 0.1              # Deterministische Antworten

```

---

## 📂 Projektstruktur

```text
polymarket_bot/
├── config/
│   ├── config.toml            # Trading- und Risikoparameter
│   └── catalog.json           # Nautilus Instrument Katalog (generiert)
├── src/
│   ├── data/                  # (WIP) Loader für historische Daten
│   ├── intelligence/
│   │   └── gemini.py          # KI-Wrapper, Prompts & JSON-Schema
│   ├── scanner/
│   │   └── polymarket.py      # API Client für Marktsuche
│   ├── strategies/
│   │   └── sentiment.py       # Trading-Logik & Event-Loop
│   ├── main.py                # Entry Point & Node Setup
│   └── notifications.py       # Telegram Bot
├── .env.example               # Template für Secrets
├── docker-compose.yml         # Container Orchestrierung
├── Dockerfile                 # Image Definition
└── requirements.txt           # Python Abhängigkeiten

```

---

## 🛡 Qualitätssicherung & Entwicklung

Das Projekt nutzt strenge Code-Quality-Tools, die via GitHub Actions oder lokal ausgeführt werden können:

* **Linting:** `flake8` (Syntax & Style)
* **Formatting:** `black` (Code-Formatierung)
* **Imports:** `isort` (Sortierung der Imports)
* **Typing:** `mypy` (Statische Typenprüfung)

Befehl zum lokalen Testen:

```bash
# Linting
flake8 src/
# Formatting Check
black --check src/
# Type Check
mypy src/ --ignore-missing-imports

```

---

## ⚠️ Risiko-Hinweis

Dieser Bot handelt mit **echten Kryptowährungen** auf der Polygon Blockchain.

* Die KI-Analyse (Gemini) ist nicht unfehlbar und kann Nachrichten falsch interpretieren.
* Vergangene Performance garantiert keine zukünftigen Ergebnisse.
* Benutzung auf eigene Gefahr. Stelle sicher, dass die Limits in der `config.toml` deinem Risikoprofil entsprechen.

---

**Lizenz:** MIT
**Maintainer:** @philibertschlutzki
