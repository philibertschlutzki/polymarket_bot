# Polymarket AI Value Bettor 🤖📈

Ein KI-gestütztes Tool, das Polymarket-Märkte analysiert, Wahrscheinlichkeiten mittels Google Gemini (inkl. Live-Websuche) berechnet und Value-Bets basierend auf dem Kelly-Kriterium identifiziert.

## 🚀 Features

* **Markt-Scanner:** Findet automatisch die liquidesten Märkte auf Polymarket via CLOB API.
* **KI-Analyse:** Nutzt Gemini 2.0 Flash mit Google Search Grounding für aktuelle Faktenanalysen.
* **Value-Erkennung:** Vergleicht KI-Wahrscheinlichkeit mit Marktpreisen.
* **Risikomanagement:** Berechnet die optimale Positionsgröße mittels Kelly-Kriterium (Hard-Cap bei 50% des Portfolios).

## 🛠 Voraussetzungen

* Python 3.10 oder höher
* Google AI Studio API Key (kostenlos verfügbar)
* Internetverbindung zur Polymarket CLOB API (clob.polymarket.com)
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
```

## 🔧 Troubleshooting

### Polymarket API nicht erreichbar

Wenn Sie die Fehlermeldung "Die Polymarket API ist in dieser Umgebung nicht erreichbar" erhalten:

1. **Überprüfen Sie Ihre Internetverbindung:**
   ```bash
   curl https://clob.polymarket.com/markets
   ```

2. **Stellen Sie sicher, dass keine Firewall die Verbindung blockiert:**
   - Einige Unternehmens- oder Schul-Netzwerke blockieren möglicherweise den Zugriff auf Polymarket
   - Versuchen Sie es mit einem anderen Netzwerk oder VPN

3. **Überprüfen Sie DNS-Auflösung:**
   ```bash
   nslookup clob.polymarket.com
   ```

4. **Verwenden Sie die neueste Version der Abhängigkeiten:**
   ```bash
   pip install --upgrade -r requirements.txt
   ```

### API Key Fehler

Wenn Sie "GEMINI_API_KEY nicht in .env gefunden!" erhalten:
- Stellen Sie sicher, dass die `.env` Datei im selben Verzeichnis wie `main.py` liegt
- Überprüfen Sie, dass der API Key korrekt eingefügt wurde (ohne Anführungszeichen)
- Erstellen Sie einen neuen API Key unter https://aistudio.google.com/app/apikey

## 📚 Technische Details

Der Bot verwendet:
- **py-clob-client**: Offizielle Python-Bibliothek für die Polymarket CLOB API
- **google-genai**: Google Gemini SDK für KI-Analysen mit Web-Suche
- **pydantic**: Datenvalidierung und -modellierung

