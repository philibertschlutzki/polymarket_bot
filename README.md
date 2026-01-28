# Polymarket AI Value Bettor 🤖📈

Ein KI-gestütztes Tool, das Polymarket-Märkte analysiert, Wahrscheinlichkeiten mittels Google Gemini (inkl. Live-Websuche) berechnet und Value-Bets basierend auf dem Kelly-Kriterium identifiziert.

## 🚀 Features

* **Markt-Scanner:** Findet automatisch die liquidesten Märkte auf Polymarket.
* **KI-Analyse:** Nutzt Gemini 2.0 Flash mit Google Search Grounding für aktuelle Faktenanalysen.
* **Value-Erkennung:** Vergleicht KI-Wahrscheinlichkeit mit Marktpreisen.
* **Risikomanagement:** Berechnet die optimale Positionsgröße mittels Kelly-Kriterium (Hard-Cap bei 50% des Portfolios).

## 🛠 Voraussetzungen

* Python 3.10 oder höher
* Google AI Studio API Key (kostenlos verfügbar)
* Polymarket Account (für spätere Ausführung)

## 📦 Installation

1.  **Repository klonen/erstellen:**
    ```bash
    git clone [https://github.com/ihr-username/polymarket-ai.git](https://github.com/ihr-username/polymarket-ai.git)
    cd polymarket-ai
    ```

2.  **Virtuelle Umgebung erstellen:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # Mac/Linux
    # oder
    venv\Scripts\activate     # Windows
    ```

3.  **Abhängigkeiten installieren:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Konfiguration:**
    Erstelle eine `.env` Datei im Hauptverzeichnis:
    ```env
    GEMINI_API_KEY=Dein_Google_Gemini_Key_Hier
    TOTAL_CAPITAL=1000  # Dein Startkapital in USDC
    ```

##  ▶️ Nutzung

Starte den Analyse-Bot:

```bash
python main.py
