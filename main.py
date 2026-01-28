# Role
Du bist ein erfahrener Python-Entwickler, spezialisiert auf quantitative Finanzmodelle, API-Integrationen und LLM-Prompting.

# Project Goal
Erstelle einen Python-Bot, der Märkte auf der Plattform "Polymarket" analysiert. Der Bot soll "Value Bets" identifizieren – also Wetten, bei denen die von einer KI (Google Gemini) geschätzte Wahrscheinlichkeit signifikant höher ist als die vom Marktpreis implizierte Wahrscheinlichkeit.

# Core Requirements
1. **Data Source:** Nutze die Polymarket Gamma API (`https://gamma-api.polymarket.com/events`), um aktive Märkte mit hohem Volumen zu finden.
2. **Analysis Engine:** Nutze die `google-generativeai` Bibliothek (Gemini 2.0 Flash).
   - Aktiviere Google Search Grounding (Tools), um aktuelle Fakten zu recherchieren.
   - Der Prompt an Gemini muss die Marktfrage und Beschreibung enthalten und eine Wahrscheinlichkeit (0.0 bis 1.0) sowie einen Confidence-Score zurückgeben.
3. **Risk Management (Crucial):**
   - Implementiere das "Fractional Kelly Criterion".
   - Formel: `f = (p * (b + 1) - 1) / b`
     - p = Wahrscheinlichkeit der KI
     - b = Netto-Odds ((1 / Marktpreis) - 1)
   - **Constraint:** Der Einsatz darf NIEMALS 50% des Gesamtkapitals überschreiten (`min(kelly_stake, 0.5 * capital)`).
4. **Output:** Der Bot soll die Analyse in der Konsole ausgeben und eine klare Kaufempfehlung (JA/NEIN/PASS) mit der berechneten Einsatzhöhe in USDC geben.

# Tech Stack
- Python 3.10+
- Libraries: `requests`, `python-dotenv`, `google-generativeai`, `pydantic` (für strukturierte Daten).
- Datei-Struktur: `main.py` (Logik), `.env` (API Keys), `requirements.txt`.

# Context
Der Nutzer möchte Wetten aus allen Themenbereichen (Krypto, Politik, Sport) abdecken. Der Code soll modular sein, damit später eine automatische Ausführung (Execution via CLOB API) hinzugefügt werden kann. Schreibe sauberen, typisierten Code mit Docstrings auf Deutsch.
