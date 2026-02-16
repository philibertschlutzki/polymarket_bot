# 🧠 Polymarket AI Trader (Nautilus & Gemini)

![Status](https://img.shields.io/badge/Status-Alpha-red)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Framework](https://img.shields.io/badge/Nautilus_Trader-Production-green)
![AI](https://img.shields.io/badge/Google-Gemini_2.0-purple)

Ein hocheffizienter, KI-gesteuerter Trading-Bot für **Polymarket** (Polygon Blockchain).
Der Bot nutzt das **Nautilus Trader Framework** für professionelles Order-Management und **Google Gemini 2.0 (mit Search Grounding)** für die Sentiment-Analyse von Nachrichten und Ereignissen.

> ⚠️ **WICHTIGER HINWEIS:**
> Dieses Repository befindet sich in einer **harten Migration** von V1 (Legacy Scripts) zu V2 (Nautilus Trader).
> Die V2-Architektur ist **Work-in-Progress (WIP)**.
>
> 👉 **Legacy Code:** Wer die alte, stabile Version sucht, findet diese im Ordner [`legacy_v1/`](legacy_v1/).

---

## 🏗 Architektur (V2 - In Development)

Das System besteht aus zwei Hauptkomponenten, die lose gekoppelt sind, um Speicher zu sparen:

1.  **Market Scanner (The Funnel):** Scannt periodisch die Polymarket API nach liquiden Märkten.
2.  **Trading Engine (Nautilus):** Führt die Handelslogik für die ausgewählten Märkte aus.

Detaillierte Infos findest du in [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## ✨ Features (Planned V2)

* **KI-Entscheidungen:** Nutzt Google Gemini 2.0 Flash mit Zugriff auf aktuelle Google-Suchergebnisse (keine Halluzinationen bei aktuellen News).
* **Smart Execution:** Nutzt *Marketable Limit Orders*, um Slippage zu vermeiden.
* **Ressourcenschonend:** Nutzt Redis als reinen In-Memory Cache.

---

## 🚀 Installation & Setup

### Voraussetzungen

Du benötigst folgende Accounts und Keys:

1. **Google Cloud:** API Key für Gemini (mit Vertex AI / AI Studio Zugriff).
2. **Polygon Wallet:** Private Key einer Wallet mit etwas POL (für Gas) und USDC.e (für Einsätze).
3. **Polymarket API:** API Key, Secret und Passphrase (erstellbar via Polymarket Profil).
4. **Telegram:** Bot Token (via @BotFather) und deine Chat ID.

### 1. Repository klonen

```bash
git clone https://github.com/philibertschlutzki/polymarket_bot.git
cd polymarket_bot
```

### 2. Konfiguration (.env)

Erstelle eine Datei `.env` im Hauptverzeichnis. **Diese Datei darf niemals auf GitHub hochgeladen werden!**

```bash
cp .env.example .env
nano .env
```

Stelle sicher, dass alle Variablen gefüllt sind (siehe `.env.example`), insbesondere `GOOGLE_API_KEY`, `POLYGON_PRIVATE_KEY` und die `POLYMARKET_API_` Keys.

### 3. Abhängigkeiten installieren

Für V2 sind `nautilus_trader` und `google-generativeai` zwingend erforderlich.

```bash
uv pip install -r requirements.txt
# oder
pip install -r requirements.txt
```

---

## 📂 Projektstruktur

```text
polymarket_bot/
├── config/
│   ├── config.toml          # Strategie-Parameter
│   └── catalog.json         # Nautilus Instrument Katalog
├── legacy_v1/               # 🏛️ Archivierte Legacy Skripte (Stable)
├── src/
│   ├── data/                # 🚧 WIP: Loader für historische Daten
│   ├── intelligence/        # ✅ Implemented: Gemini API Wrapper & Prompts
│   ├── scanner/             # 🚧 WIP: Polymarket API Filter (Der Trichter)
│   ├── strategies/          # ✅ Implemented: Nautilus Strategy Klassen
│   └── main.py              # 🚧 WIP: Entry Point
├── docker-compose.yml       # Docker Orchestrierung
├── Dockerfile               # Image Definition
├── requirements.txt         # Python Libraries
├── ARCHITECTURE.md          # Architektur-Details
└── CONTRIBUTING.md          # Migrations-Guide
```

---

## 🤝 Contributing

Wir suchen Hilfe bei der Migration! Siehe [`CONTRIBUTING.md`](CONTRIBUTING.md) für Details, wie du beim Portieren der Scanner-Logik helfen kannst.

---

## ⚠️ Disclaimer & Risiko

Dieser Bot handelt mit echtem Geld (Kryptowährungen).

* **Benutzung auf eigene Gefahr.**
* Die KI (Gemini) kann Fehler machen oder Nachrichten falsch interpretieren.
* Vergangene Performance im Backtest garantiert keine zukünftigen Gewinne.
* Stelle sicher, dass du die `max_trade_usdc` Limits entsprechend deiner Risikotoleranz setzt.

---

**Lizenz:** MIT
**Maintainer:** @philibertschlutzki
